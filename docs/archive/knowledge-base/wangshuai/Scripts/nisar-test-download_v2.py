"""
NISAR RSLC 云端预览 + 远程裁剪下载 (v3 修正版)
================================================
修正: validSamplesSubSwath 等 swaths 下数据集未正确裁剪
原因: _deep_copy_small 先全量复制再修补的策略不可靠
方案: 元数据和 swaths 分开处理, swaths 从头构建, 每个数据集明确裁剪

流程:
  1. 远程读取 geolocationGrid → 计算裁剪窗口
  2. 远程读取降采样预览 → 可视化 (确认区域)
  3. 远程直接读取裁剪范围数据, 只下载需要的部分

Author: Shuai Wang (China University of Mining and Technology)
"""

import os, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import h5py
import numpy as np
from scipy.interpolate import RegularGridInterpolator

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

# ─────────────────────────────────────────────────────────────────────────────
POL_NAMES = frozenset({'HH', 'HV', 'VH', 'VV', 'RH', 'RV', 'LH', 'LV'})
# swaths 路径链, 用于分离元数据和 swaths
SWATHS_PATH = 'science/LSAR/RSLC/swaths'
SWATHS_CHAIN = ('science', 'LSAR', 'RSLC', 'swaths')


############################################################################
# P1: 远程预览
############################################################################
def _open_remote(url, max_retries=5, block_size_mb=128,
                 cache_size_mb=512, hdf5_cache_mb=256):
    """打开远程 HDF5, 带重试 + 更大的缓存/块大小"""
    import fsspec
    for attempt in range(1, max_retries + 1):
        try:
            print(f"    连接 ({attempt}/{max_retries})...", end='', flush=True)
            fs = fsspec.filesystem(
                "https",
                client_kwargs={
                    "trust_env": True,
                    "timeout": None,
                },
                block_size=block_size_mb * 1024 * 1024,
                cache_type='bytes',
            )
            f = fs.open(url, "rb")
            h5f = h5py.File(
                f, "r",
                rdcc_nbytes=hdf5_cache_mb * 1024 * 1024,
                rdcc_nslots=200_000,
            )
            print(f" OK")
            return f, h5f
        except Exception as e:
            print(f" ERROR {type(e).__name__}: {e}")
            if attempt < max_retries:
                wait = attempt * 5
                print(f"    等待 {wait}s 后重试...")
                time.sleep(wait)
            else:
                raise RuntimeError(
                    f"连接失败 ({max_retries} 次): {e}\n"
                    "建议: 1) 检查 ~/.netrc 认证  "
                    "2) 检查网络  3) 尝试 VPN"
                ) from e


def bbox_to_radar_window(h5f, bbox, freq='A', margin=20, height_index=1,
                         refine=20):
    """
    用 geolocationGrid 把经纬度 → 行列号。
    使用细化插值 (refine 倍), 避免粗网格遗漏边界。
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    sw = SWATHS_PATH

    geo = h5f['science/LSAR/RSLC/metadata/geolocationGrid']
    grid_zt = geo['zeroDopplerTime'][:]
    grid_sr = geo['slantRange'][:]
    lon_grid = geo['coordinateX'][height_index]
    lat_grid = geo['coordinateY'][height_index]

    # 构建插值器
    interp_lon = RegularGridInterpolator(
        (grid_zt, grid_sr), lon_grid, method='linear',
        bounds_error=False, fill_value=np.nan)
    interp_lat = RegularGridInterpolator(
        (grid_zt, grid_sr), lat_grid, method='linear',
        bounds_error=False, fill_value=np.nan)

    # 粗略定位: 找 bbox 附近的网格区域
    coarse_mask = ((lon_grid >= min_lon - 0.5) & (lon_grid <= max_lon + 0.5) &
                   (lat_grid >= min_lat - 0.5) & (lat_grid <= max_lat + 0.5))

    if np.any(coarse_mask):
        az_idx = np.where(np.any(coarse_mask, axis=1))[0]
        rg_idx = np.where(np.any(coarse_mask, axis=0))[0]
        pad = 3
        az_lo = max(0, az_idx.min() - pad)
        az_hi = min(len(grid_zt) - 1, az_idx.max() + pad)
        rg_lo = max(0, rg_idx.min() - pad)
        rg_hi = min(len(grid_sr) - 1, rg_idx.max() + pad)
    else:
        az_lo, az_hi = 0, len(grid_zt) - 1
        rg_lo, rg_hi = 0, len(grid_sr) - 1

    zt_sub = grid_zt[az_lo:az_hi+1]
    sr_sub = grid_sr[rg_lo:rg_hi+1]

    # 细化采样
    fine_n_az = len(zt_sub) * refine
    fine_n_rg = len(sr_sub) * refine
    fine_zt = np.linspace(zt_sub[0], zt_sub[-1], fine_n_az)
    fine_sr = np.linspace(sr_sub[0], sr_sub[-1], fine_n_rg)

    zt_mesh, sr_mesh = np.meshgrid(fine_zt, fine_sr, indexing='ij')
    pts = np.column_stack([zt_mesh.ravel(), sr_mesh.ravel()])

    fine_lon = interp_lon(pts).reshape(fine_n_az, fine_n_rg)
    fine_lat = interp_lat(pts).reshape(fine_n_az, fine_n_rg)

    bbox_mask = ((fine_lon >= min_lon) & (fine_lon <= max_lon) &
                 (fine_lat >= min_lat) & (fine_lat <= max_lat))

    if not np.any(bbox_mask):
        raise RuntimeError(
            f"bbox {bbox} 不在数据覆盖范围内!\n"
            f"数据范围: lon=[{np.nanmin(fine_lon):.2f}, {np.nanmax(fine_lon):.2f}], "
            f"lat=[{np.nanmin(fine_lat):.2f}, {np.nanmax(fine_lat):.2f}]")

    az_in = np.where(np.any(bbox_mask, axis=1))[0]
    rg_in = np.where(np.any(bbox_mask, axis=0))[0]

    zt_min = fine_zt[az_in.min()]
    zt_max = fine_zt[az_in.max()]
    sr_min = fine_sr[rg_in.min()]
    sr_max = fine_sr[rg_in.max()]

    # 转为像素行列号
    swath_zt = h5f[f'{sw}/zeroDopplerTime'][:]
    swath_sr = h5f[f'{sw}/frequency{freq}/slantRange'][:]

    for pol in POL_NAMES:
        if f'{sw}/frequency{freq}/{pol}' in h5f:
            n_az, n_rg = h5f[f'{sw}/frequency{freq}/{pol}'].shape
            break
    else:
        raise RuntimeError(f"frequency{freq} 下无极化数据")

    az_s = max(0, int(np.searchsorted(swath_zt, zt_min)) - margin)
    az_e = min(n_az, int(np.searchsorted(swath_zt, zt_max, side='right')) + margin)
    rg_s = max(0, int(np.searchsorted(swath_sr, sr_min)) - margin)
    rg_e = min(n_rg, int(np.searchsorted(swath_sr, sr_max, side='right')) + margin)

    return {
        'az_start': az_s, 'az_end': az_e,
        'rg_start': rg_s, 'rg_end': rg_e,
        'n_az_orig': n_az, 'n_rg_orig': n_rg,
        'grid_zt': grid_zt, 'grid_sr': grid_sr,
        'lon_grid': lon_grid, 'lat_grid': lat_grid,
    }


def preview_remote(url, bbox, freq='A', margin=20, downsample=10,
                   save_dir='.', height_index=1,
                   block_size_mb=128, cache_size_mb=512, hdf5_cache_mb=256):
    """远程预览"""
    name = os.path.basename(url)
    base = os.path.splitext(name)[0]

    f_obj, h5f = None, None
    try:
        f_obj, h5f = _open_remote(
            url, block_size_mb=block_size_mb,
            cache_size_mb=cache_size_mb, hdf5_cache_mb=hdf5_cache_mb,
        )
        sw = SWATHS_PATH

        print(f"    计算裁剪范围...", end='', flush=True)
        info = bbox_to_radar_window(h5f, bbox, freq=freq, margin=margin,
                                    height_index=height_index)
        n_az_c = info['az_end'] - info['az_start']
        n_rg_c = info['rg_end'] - info['rg_start']
        pct = 100 * n_az_c * n_rg_c / (info['n_az_orig'] * info['n_rg_orig'])
        est_mb = n_az_c * n_rg_c * 8 / 1024 / 1024
        print(f" OK")
        print(f"    原始: {info['n_az_orig']}×{info['n_rg_orig']}")
        print(f"    裁剪: {n_az_c}×{n_rg_c} ({pct:.2f}%, ~{est_mb:.0f}MB)")

        ds = downsample
        az_s, az_e = info['az_start'], info['az_end']
        rg_s, rg_e = info['rg_start'], info['rg_end']

        for pol in ['HH', 'HV', 'VV', 'VH']:
            key = f'{sw}/frequency{freq}/{pol}'
            if key in h5f:
                print(f"    读取预览 freq{freq}/{pol} "
                      f"(1/{ds} 降采样)...", end='', flush=True)
                t0 = time.time()
                slc = h5f[key][az_s:az_e:ds, rg_s:rg_e:ds]
                mb = slc.nbytes / 1024 / 1024
                print(f" {slc.shape} ({mb:.1f}MB, {time.time()-t0:.1f}s)")
                pol_name = pol
                break

        amp = np.abs(slc).astype(np.float32)
        amp[amp == 0] = np.nan
        amp_db = 20.0 * np.log10(amp)

        print(f"    地理编码...", end='', flush=True)
        interp_lon = RegularGridInterpolator(
            (info['grid_zt'], info['grid_sr']), info['lon_grid'],
            method='linear', bounds_error=False)
        interp_lat = RegularGridInterpolator(
            (info['grid_zt'], info['grid_sr']), info['lat_grid'],
            method='linear', bounds_error=False)

        crop_zt = h5f[f'{sw}/zeroDopplerTime'][az_s:az_e:ds]
        crop_sr = h5f[f'{sw}/frequency{freq}/slantRange'][rg_s:rg_e:ds]
        n_az_p, n_rg_p = slc.shape
        crop_zt = crop_zt[:n_az_p]
        crop_sr = crop_sr[:n_rg_p]

        zt_m, sr_m = np.meshgrid(crop_zt, crop_sr, indexing='ij')
        pts = np.column_stack([zt_m.ravel(), sr_m.ravel()])
        lon_2d = interp_lon(pts).reshape(n_az_p, n_rg_p)
        lat_2d = interp_lat(pts).reshape(n_az_p, n_rg_p)
        print(f" OK")

        min_lon, min_lat, max_lon, max_lat = bbox
        vmin = max(np.nanmedian(amp_db) - 15, -30)
        vmax = np.nanmedian(amp_db) + 15

        fig, axes = plt.subplots(1, 2, figsize=(18, 8))
        axes[0].imshow(amp_db, cmap='gray', vmin=vmin, vmax=vmax, aspect='auto')
        axes[0].set_title(f'Radar coords: freq{freq}/{pol_name}\n'
                          f'crop: {n_az_c}×{n_rg_c} / '
                          f'{info["n_az_orig"]}×{info["n_rg_orig"]}')
        axes[0].set_xlabel('Range (px)')
        axes[0].set_ylabel('Azimuth (px)')

        valid = np.isfinite(lon_2d) & np.isfinite(lat_2d)
        if np.sum(valid) > 100:
            axes[1].pcolormesh(lon_2d, lat_2d, amp_db, cmap='gray',
                               vmin=vmin, vmax=vmax, shading='auto')
            rect = Rectangle((min_lon, min_lat),
                              max_lon - min_lon, max_lat - min_lat,
                              lw=2, ec='red', fc='none', ls='--', label='bbox')
            axes[1].add_patch(rect)
            axes[1].legend(fontsize=10)
            axes[1].set_xlabel('Longitude (°E)')
            axes[1].set_ylabel('Latitude (°N)')
            axes[1].set_aspect('equal')
            act_lon = (np.nanmin(lon_2d[valid]), np.nanmax(lon_2d[valid]))
            act_lat = (np.nanmin(lat_2d[valid]), np.nanmax(lat_2d[valid]))
            covers = (act_lon[0] <= min_lon and act_lon[1] >= max_lon and
                      act_lat[0] <= min_lat and act_lat[1] >= max_lat)
            status = "✅ 完全覆盖" if covers else "⚠️ 部分覆盖"
            axes[1].set_title(
                f'Geocoded preview  {status}\n'
                f'bbox: {min_lon:.2f}~{max_lon:.2f}°E, '
                f'{min_lat:.2f}~{max_lat:.2f}°N\n'
                f'actual: {act_lon[0]:.2f}~{act_lon[1]:.2f}°E, '
                f'{act_lat[0]:.2f}~{act_lat[1]:.2f}°N')

        plt.tight_layout()
        fig_path = os.path.join(save_dir, f"{base}_preview.png")
        plt.savefig(fig_path, dpi=150, bbox_inches='tight')
        plt.close(fig)
        print(f"    PREVIEW: {fig_path}")
        return info

    except Exception as e:
        print(f"    ERROR 预览失败: {e}")
        import traceback; traceback.print_exc()
        return None
    finally:
        if h5f is not None:
            try: h5f.close()
            except: pass
        if f_obj is not None:
            try: f_obj.close()
            except: pass


############################################################################
# P2: 裁剪下载 (修正版: swaths 从头构建, 不依赖后修补)
############################################################################
def _copy_attrs(src, dst):
    for k, v in src.attrs.items():
        try: dst.attrs[k] = v
        except: pass


def _crop_valid_samples(arr, rg_start, n_rg_crop):
    """裁剪 validSamplesSubSwath: 偏移 range 起点并 clip"""
    a = arr.astype(np.int64)
    a[:, 0] -= rg_start
    a[:, 1] -= rg_start
    np.clip(a[:, 0], 0, n_rg_crop, out=a[:, 0])
    np.clip(a[:, 1], 0, n_rg_crop, out=a[:, 1])
    a[a[:, 0] >= a[:, 1]] = 0
    return a.astype(np.uint32)


def _write_ds(grp, name, data, src_ds=None):
    """写入数据集 + 复制属性"""
    if name in grp:
        del grp[name]
    kw = {}
    if isinstance(data, np.ndarray) and data.ndim > 0 and data.nbytes > 50000:
        kw = dict(compression='lzf', chunks=True)
    try:
        ds = grp.create_dataset(name, data=data, **kw)
    except:
        ds = grp.create_dataset(name, data=data)
    if src_ds is not None:
        _copy_attrs(src_ds, ds)
    return ds


def _copy_tree_except_swaths(src_grp, dst_grp, depth=0):
    """
    递归复制 HDF5 树, 但跳过 swaths 子树的内容。
    只创建到 swaths 为止的空 group 结构。
    """
    _copy_attrs(src_grp, dst_grp)
    target = SWATHS_CHAIN[depth] if depth < len(SWATHS_CHAIN) else None

    for key in src_grp:
        item = src_grp[key]
        if isinstance(item, h5py.Group):
            if key == target:
                # 到达 swaths 路径上的 group → 只创建空 group, 继续递归
                sub = dst_grp.require_group(key)
                _copy_attrs(item, sub)
                if depth + 1 < len(SWATHS_CHAIN):
                    _copy_tree_except_swaths(item, sub, depth + 1)
                # depth == len(SWATHS_CHAIN)-1 时, 即到达 swaths → 不复制内容
            else:
                # 非 swaths 路径 → 整组拷贝
                try:
                    src_grp.copy(key, dst_grp)
                except Exception as e:
                    # 拷贝失败则递归
                    sub = dst_grp.require_group(key)
                    _copy_tree_except_swaths(item, sub, depth=999)
        elif isinstance(item, h5py.Dataset):
            if depth < len(SWATHS_CHAIN):
                # swaths 路径上的非 group 数据集 → 直接复制
                try:
                    data = item[()]
                    _write_ds(dst_grp, key, data, item)
                except:
                    pass


def _read_with_retry(dataset, slices, max_retries=5, desc=""):
    """带重试的远程数据读取"""
    for attempt in range(1, max_retries + 1):
        try:
            return dataset[slices]
        except Exception as e:
            if attempt < max_retries:
                wait = attempt * 3
                print(f"\n      WARN 读取失败 ({type(e).__name__}), "
                      f"等待 {wait}s 重试 ({attempt}/{max_retries})...",
                      end='', flush=True)
                time.sleep(wait)
            else:
                raise RuntimeError(f"读取失败 ({max_retries} 次): {e}") from e


def _parallel_download_slc(url, dataset_path, az_start, az_end, rg_start, rg_end,
                           n_workers=16, chunk_rows=256, block_size_mb=32):
    """多线程并行下载 SLC 数据块"""
    import fsspec

    n_az = az_end - az_start
    n_rg = rg_end - rg_start

    chunks = []
    for i in range(0, n_az, chunk_rows):
        c_az_start = az_start + i
        c_az_end = min(az_start + i + chunk_rows, az_end)
        chunks.append((c_az_start, c_az_end))

    result = np.empty((n_az, n_rg), dtype=np.complex64)
    lock = threading.Lock()
    progress = {'done': 0, 'bytes': 0, 'start_time': time.time()}

    def download_chunk(chunk_idx, c_az_start, c_az_end):
        local_az_start = c_az_start - az_start
        local_az_end = c_az_end - az_start
        for attempt in range(1, 4):
            try:
                fs = fsspec.filesystem("https", client_kwargs={
                    "trust_env": True, "timeout": None,
                }, block_size=block_size_mb * 1024 * 1024)
                with fs.open(url, "rb") as f:
                    with h5py.File(f, "r") as h5f:
                        data = h5f[dataset_path][c_az_start:c_az_end, rg_start:rg_end]
                        result[local_az_start:local_az_end, :] = data
                with lock:
                    progress['done'] += 1
                    progress['bytes'] += data.nbytes
                    elapsed = time.time() - progress['start_time']
                    speed = progress['bytes'] / 1024 / 1024 / elapsed if elapsed > 0 else 0
                    pct = 100 * progress['done'] / len(chunks)
                    print(f"\r       下载: {progress['done']}/{len(chunks)} ({pct:.0f}%) "
                          f"速度: {speed:.1f} MB/s    ", end='', flush=True)
                return True
            except Exception as e:
                if attempt < 3:
                    time.sleep(attempt * 2)
                else:
                    print(f"\n       WARN chunk {chunk_idx} 失败: {e}")
                    return False
        return False

    print(f" [{len(chunks)} chunks × {n_workers} workers]")
    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        futures = [executor.submit(download_chunk, i, c[0], c[1])
                   for i, c in enumerate(chunks)]
        for f in as_completed(futures):
            f.result()
    print()
    return result


def download_cropped(h5f, output_h5, freq_info, bbox, url=None,
                     n_workers=16, chunk_rows=256):
    """
    从远程 h5f 下载裁剪数据到本地。

    修正版策略:
      Phase 1: 复制 swaths 以外的全部元数据 (identification, metadata, orbit 等)
      Phase 2: 从头构建 swaths, 每个数据集明确裁剪
               → 不存在 "先复制全量再修补" 的遗漏风险
    """
    sw = SWATHS_PATH
    os.makedirs(os.path.dirname(output_h5) or '.', exist_ok=True)

    if os.path.exists(output_h5):
        try:
            os.remove(output_h5)
        except Exception as e:
            base, ext = os.path.splitext(output_h5)
            output_h5 = f"{base}_{int(time.time())}{ext}"
            print(f"    使用新文件名: {os.path.basename(output_h5)}")

    # 获取原始维度
    fk0 = list(freq_info.keys())[0]
    info0 = freq_info[fk0]
    n_az_orig = info0['n_az_orig']

    with h5py.File(output_h5, 'w') as dst:

        # ================================================================
        # Phase 1: 复制 swaths 以外的所有内容
        # ================================================================
        print(f"    Phase 1: 元数据...", end='', flush=True)
        t1 = time.time()
        _copy_tree_except_swaths(h5f, dst, depth=0)
        print(f" OK ({time.time()-t1:.1f}s)")

        # ================================================================
        # Phase 2: 从头构建 swaths (每个数据集明确处理)
        # ================================================================
        print(f"    Phase 2: 构建 swaths (裁剪):")
        src_sw = h5f[sw]
        dst_sw = dst.require_group(sw)
        _copy_attrs(src_sw, dst_sw)

        # ── 2a: swaths 直属数据集 ──
        az_sl_0 = slice(info0['az_start'], info0['az_end'])
        n_az_crop = info0['az_end'] - info0['az_start']
        n_rg_c0 = info0['rg_end'] - info0['rg_start']

        for key in src_sw:
            item = src_sw[key]
            if isinstance(item, h5py.Group):
                continue  # frequencyA/B 单独处理
            if not isinstance(item, h5py.Dataset):
                continue

            # 根据维度决定如何裁剪
            if key.startswith('validSamplesSubSwath') and item.ndim == 2 and item.shape[1] == 2:
                # validSamples: azimuth 裁剪 + range 偏移
                raw = _read_with_retry(item, (az_sl_0, slice(None)))
                data = _crop_valid_samples(raw, info0['rg_start'], n_rg_c0)
                print(f"      swaths/{key}: {item.shape} → {data.shape}")
            elif item.ndim >= 1 and item.shape[0] == n_az_orig:
                # 方位向维度匹配 → 裁剪
                if item.ndim == 1:
                    data = _read_with_retry(item, az_sl_0)
                else:
                    data = _read_with_retry(item, (az_sl_0, slice(None)))
                print(f"      swaths/{key}: {item.shape} → {data.shape}")
            else:
                # 标量或其他 → 原样复制
                data = item[()]

            _write_ds(dst_sw, key, data, item)

        # ── 2b: 每个频率组 ──
        for fk, info in freq_info.items():
            fq_path = f'{sw}/frequency{fk}'
            if fq_path not in h5f:
                print(f"      ⚠️ {fq_path} 不存在, 跳过")
                continue

            src_fq = h5f[fq_path]
            dst_fq = dst.require_group(fq_path)
            _copy_attrs(src_fq, dst_fq)

            n_rg_orig = info['n_rg_orig']
            n_rg_c = info['rg_end'] - info['rg_start']
            az_sl = slice(info['az_start'], info['az_end'])
            rg_sl = slice(info['rg_start'], info['rg_end'])

            print(f"\n      frequency{fk}: 遍历数据集...")

            for key in src_fq:
                item = src_fq[key]

                # ── Group → 整组复制 (listOfPolarizations 等) ──
                if isinstance(item, h5py.Group):
                    if key not in dst_fq:
                        try:
                            src_fq.copy(key, dst_fq)
                        except:
                            pass
                    continue

                if not isinstance(item, h5py.Dataset):
                    continue

                # ── SLC 极化数据 (大) ──
                if key in POL_NAMES and item.ndim == 2:
                    print(f"       freq{fk}/{key} {item.shape}...", end='', flush=True)
                    t3 = time.time()
                    n_az_c = info['az_end'] - info['az_start']

                    if url is not None:
                        dataset_path = f'{fq_path}/{key}'
                        data = _parallel_download_slc(
                            url, dataset_path,
                            info['az_start'], info['az_end'],
                            info['rg_start'], info['rg_end'],
                            n_workers=n_workers, chunk_rows=chunk_rows,
                        )
                    else:
                        data = _read_with_retry(item, (az_sl, rg_sl))

                    _write_ds(dst_fq, key, data, item)
                    mb = data.nbytes / 1024 / 1024
                    dt = time.time() - t3
                    spd = mb / dt if dt > 0 else 0
                    print(f"       done → {data.shape} "
                          f"({mb:.0f}MB {dt:.1f}s 平均 {spd:.1f}MB/s)")
                    continue

                # ── validSamplesSubSwath (关键!) ──
                if key.startswith('validSamplesSubSwath') and item.ndim == 2 and item.shape[1] == 2:
                    raw = _read_with_retry(item, (az_sl, slice(None)))
                    data = _crop_valid_samples(raw, info['rg_start'], n_rg_c)
                    print(f"       freq{fk}/{key}: {item.shape} → {data.shape}")

                # ── slantRange (range 方向裁剪) ──
                elif item.ndim == 1 and item.shape[0] == n_rg_orig:
                    data = _read_with_retry(item, rg_sl)
                    print(f"       freq{fk}/{key}: {item.shape} → {data.shape}")

                # ── 2D, 方位×距离 (如 numberSubSwaths 等) ──
                elif item.ndim == 2 and item.shape[0] == n_az_orig:
                    if item.shape[1] == n_rg_orig:
                        data = _read_with_retry(item, (az_sl, rg_sl))
                    else:
                        data = _read_with_retry(item, (az_sl, slice(None)))
                    print(f"       freq{fk}/{key}: {item.shape} → {data.shape}")

                # ── 1D 方位向 ──
                elif item.ndim == 1 and item.shape[0] == n_az_orig:
                    data = _read_with_retry(item, az_sl)
                    print(f"       freq{fk}/{key}: {item.shape} → {data.shape}")

                # ── 标量或其他 → 原样 ──
                else:
                    data = item[()]

                _write_ds(dst_fq, key, data, item)

    # ── 统计 ──
    sz = os.path.getsize(output_h5)
    for u in ['B', 'KB', 'MB', 'GB']:
        if sz < 1024: break
        sz /= 1024
    print(f"\n    OK 已保存: {output_h5} ({sz:.1f} {u})")

    # ── 验证: 检查所有维度一致性 ──
    print(f"    验证维度一致性...")
    _verify_dimensions(output_h5, freq_info)

    return output_h5


def _verify_dimensions(h5_path, freq_info):
    """
    验证裁剪后文件的维度一致性。
    确保所有数据集的方位向/距离向维度正确。
    """
    errors = []
    with h5py.File(h5_path, 'r') as f:
        sw = SWATHS_PATH
        if sw not in f:
            print(f"      ❌ {sw} 不存在!")
            return

        # 获取参考维度
        zt = f[f'{sw}/zeroDopplerTime']
        n_az_expected = zt.shape[0]

        # 检查 swaths 直属数据集
        for key in f[sw]:
            item = f[sw][key]
            if isinstance(item, h5py.Dataset):
                if key.startswith('validSamples') and item.ndim == 2:
                    if item.shape[0] != n_az_expected:
                        errors.append(
                            f"swaths/{key}: az={item.shape[0]} "
                            f"(期望 {n_az_expected})")
                elif item.ndim >= 1 and 'Time' in key:
                    if item.shape[0] != n_az_expected:
                        errors.append(
                            f"swaths/{key}: len={item.shape[0]} "
                            f"(期望 {n_az_expected})")

        # 检查每个频率
        for fk, info in freq_info.items():
            fq = f'{sw}/frequency{fk}'
            if fq not in f:
                continue

            n_rg_expected = info['rg_end'] - info['rg_start']

            for key in f[fq]:
                item = f[fq][key]
                if not isinstance(item, h5py.Dataset):
                    continue

                if key in POL_NAMES and item.ndim == 2:
                    if item.shape[0] != n_az_expected:
                        errors.append(
                            f"freq{fk}/{key}: az={item.shape[0]} "
                            f"(期望 {n_az_expected})")
                    if item.shape[1] != n_rg_expected:
                        errors.append(
                            f"freq{fk}/{key}: rg={item.shape[1]} "
                            f"(期望 {n_rg_expected})")

                elif key.startswith('validSamples') and item.ndim == 2:
                    if item.shape[0] != n_az_expected:
                        errors.append(
                            f"freq{fk}/{key}: az={item.shape[0]} "
                            f"(期望 {n_az_expected}) ← 致命错误!")

                elif key == 'slantRange' and item.ndim == 1:
                    if item.shape[0] != n_rg_expected:
                        errors.append(
                            f"freq{fk}/{key}: rg={item.shape[0]} "
                            f"(期望 {n_rg_expected})")

    if errors:
        print(f"      ❌ 维度不一致:")
        for e in errors:
            print(f"         {e}")
        raise RuntimeError(
            f"裁剪后文件维度不一致! 发现 {len(errors)} 个问题:\n"
            + "\n".join(errors))
    else:
        print(f"      ✅ 所有维度一致 (az={n_az_expected})")


############################################################################
# 主函数
############################################################################
def nisar_crop(bbox, urls, output_dir='./RSLC-cropped',
               freq='A', margin=20, downsample=10,
               preview_only=False, skip_preview=False,
               block_size_mb=128, cache_size_mb=512, hdf5_cache_mb=256,
               n_workers=16, chunk_rows=256):
    """
    NISAR RSLC 远程裁剪下载。

    Parameters
    ----------
    bbox : tuple - (min_lon, min_lat, max_lon, max_lat)
    urls : list[str] - RSLC 文件 URL
    output_dir : str
    freq : str - 'A' 或 'B'
    margin : int - 安全边距 (px)
    downsample : int - 预览降采样
    preview_only : bool - True=只预览
    skip_preview : bool - True=跳过预览直接下载
    n_workers : int - 并行下载线程数
    chunk_rows : int - 每块行数
    """
    os.makedirs(output_dir, exist_ok=True)
    preview_dir = os.path.join(output_dir, '_preview')
    os.makedirs(preview_dir, exist_ok=True)

    print(f"""
##########################################################
#  NISAR RSLC 远程裁剪下载 v3
#  bbox: {str(bbox)}
#  文件: {len(urls)} 景
#  freq: {freq}   margin: {margin}px
#  策略: swaths 从头构建, 不依赖后修补
##########################################################
""")

    ok = fail = 0

    for i, url in enumerate(urls, 1):
        name = os.path.basename(url)
        base = os.path.splitext(name)[0]

        print(f"\n{'='*60}")
        print(f"  [{i}/{len(urls)}] {name}")
        print(f"{'='*60}")

        f_obj = None
        h5f = None
        try:
            f_obj, h5f = _open_remote(
                url, block_size_mb=block_size_mb,
                cache_size_mb=cache_size_mb, hdf5_cache_mb=hdf5_cache_mb,
            )

            print(f"\n  计算裁剪范围:")
            info = bbox_to_radar_window(h5f, bbox, freq=freq, margin=margin)

            n_az_c = info['az_end'] - info['az_start']
            n_rg_c = info['rg_end'] - info['rg_start']
            pct = 100 * n_az_c * n_rg_c / (info['n_az_orig'] * info['n_rg_orig'])
            est_mb = n_az_c * n_rg_c * 8 / 1024 / 1024

            print(f"    原始: {info['n_az_orig']}×{info['n_rg_orig']}")
            print(f"    裁剪: {n_az_c}×{n_rg_c} ({pct:.2f}%)")
            print(f"    预估下载: ~{est_mb:.0f} MB (仅 frequency{freq})")

            if not skip_preview:
                print(f"\n  生成预览:")
                try:
                    preview_remote(
                        url, bbox, freq=freq, margin=margin,
                        downsample=downsample, save_dir=preview_dir,
                        block_size_mb=block_size_mb,
                        cache_size_mb=cache_size_mb,
                        hdf5_cache_mb=hdf5_cache_mb,
                    )
                except Exception as e:
                    print(f"    WARN 预览失败 (不影响下载): {e}")
            else:
                print(f"\n  跳过预览")

            if not preview_only:
                print(f"\n  远程裁剪下载 ({n_workers} 线程并行):")
                out_h5 = os.path.join(output_dir, f"{base}_cropped.h5")
                freq_info = {freq: info}
                t0 = time.time()

                download_cropped(h5f, out_h5, freq_info, bbox, url=url,
                                 n_workers=n_workers, chunk_rows=chunk_rows)
                print(f"    总耗时: {time.time()-t0:.1f}s")

                # isce3 验证
                try:
                    from nisar.products.readers import SLC
                    test = SLC(hdf5file=out_h5)
                    g = test.getRadarGrid(freq)
                    print(f"    ✅ SLC.getRadarGrid: {g.length}×{g.width}")
                except Exception as e:
                    print(f"    ❌ SLC 验证失败: {e}")
                    fail += 1
                    continue

                ok += 1

        except Exception as e:
            print(f"  ERROR {e}")
            import traceback; traceback.print_exc()
            fail += 1

        finally:
            if h5f is not None:
                try: h5f.close()
                except: pass
            if f_obj is not None:
                try: f_obj.close()
                except: pass

    if preview_only:
        print(f"\n  PREVIEW 预览图: {preview_dir}/")
        print(f"  设置 preview_only=False 重新运行以下载数据")
    else:
        print(f"""
##########################################################
#  完成!
#  ✅ 成功: {ok}   ❌ 失败: {fail}
#  输出: {output_dir}
##########################################################
""")


###########################################################################
if __name__ == "__main__":

    BBOX = (40.6, 13.5, 40.8, 13.78)

    BASE = ("https://nisar.asf.earthdatacloud.nasa.gov/"
            "NISAR/NISAR_L1_RSLC_BETA_V1/")

    URLS = [
        BASE + "NISAR_L1_PR_RSLC_005_172_A_008_2005_DHDH_A_20251122T024618_20251122T024652_X05007_N_F_J_001/"
               "NISAR_L1_PR_RSLC_005_172_A_008_2005_DHDH_A_20251122T024618_20251122T024652_X05007_N_F_J_001.h5",
        BASE + "NISAR_L1_PR_RSLC_006_172_A_008_2005_DHDH_A_20251204T024618_20251204T024653_X05007_N_F_J_001/"
               "NISAR_L1_PR_RSLC_006_172_A_008_2005_DHDH_A_20251204T024618_20251204T024653_X05007_N_F_J_001.h5",
    ]

    nisar_crop(
        bbox=BBOX,
        urls=URLS,
        output_dir='./RSLC-cropped',
        freq='A',
        margin=20,
        downsample=10,
        preview_only=False,
        skip_preview=True,
        block_size_mb=128,
        cache_size_mb=512,
        hdf5_cache_mb=256,
        n_workers=8,
        chunk_rows=256,
    )