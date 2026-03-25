#!/usr/bin/env bash
set -euo pipefail
###############################################################################
  #echo "  GAMMA Sentinel-1 TOPS Pre-Processing Script"
  #echo "  Author: Shuai Wang"
  #echo "  Affiliation: China University of Mining and Technology"
  #echo "  Time: 2026/01/01"
###############################################################################
# GAMMA2019 Sentinel-1 TOPS full preprocessing pipeline#
# Flow:
#   RAW(.zip/.SAFE) -> safe.list -> S1_TOPS_preproc
#   -> build data_tab & *_slc1 -> burst extract (SLC_copy_S1_TOPS)
#   -> EOF auto-download (eof / sentineleof) -> auto-pick EOF per par -> S1_OPOD_vec
#   -> mosaic (multi_S1_TOPS, SLC_mosaic_S1_TOPS)
#   -> DEM auto-download by SLC coverage (SLC_corners + eio clip) -> srtm2dem
#   -> DEM coarse+fine registration (gc_map + pixel_area + create_diff_par + offsets + gc_map_fine)
#   -> Coreg (ScanSAR_coreg.py OR S1_coreg_TOPS) -> RSLC
#   -> Deramp (S1_deramp_TOPS_reference + S1_deramp_TOPS_slave)
#   -> Archive final stack to RSLC/slc/
#
# Final outputs (PREPROCESSING OVER):
#   WORK/SLC/burst/RSLC/slc/YYYYMMDD.slc  + YYYYMMDD.slc.par
# Extra:
#   WORK/SLC/burst/RSLC/deramp/   (kept deramp intermediates/backup)
###############################################################################

############################
# 0) USER CONFIG (EDIT HERE)
############################
RAW_DIR="${RAW_DIR:-$(pwd)/RAW}"          # contains *.zip or *.SAFE
WORK_DIR="${WORK_DIR:-$(pwd)/WORK}"       # working dir

POL="${POL:-vv}"                          # vv/vh/hh/hv
MASTER="${MASTER:-20211122}"              # YYYYMMDD, empty => auto choose first date (stage2)
RLKS="${RLKS:-20}"                        # range looks
AZLKS="${AZLKS:-5}"                       # azimuth looks

# Keep which IW(s): space-separated numbers: "1" or "2" or "1 2 3"
IW_KEEP_STR="${IW_KEEP_STR:-3}"
read -r -a IW_KEEP <<< "$IW_KEEP_STR"

# Burst ranges: one line per kept IW(s): "first last"
# Example (only IW2): $'1 3'
BURST_TAB_CONTENT="${BURST_TAB_CONTENT:-$'1 1'}"

# Coreg mode: scansar_py (ScanSAR_coreg.py) OR s1_coreg_tops (S1_coreg_TOPS)
COREG_MODE="${COREG_MODE:-s1_coreg_tops}"

# ScanSAR_coreg.py params
SS_CC="${SS_CC:-0.8}"
SS_FRACTION="${SS_FRACTION:-0.02}"
SS_PHSTD="${SS_PHSTD:-0.8}"
SS_NR="${SS_NR:-128}"
SS_NAZ="${SS_NAZ:-128}"
SS_RWIN="${SS_RWIN:-256}"
SS_AZWIN="${SS_AZWIN:-256}"
SS_NO_INT="${SS_NO_INT:-1}"               # 1 => add --no_int

# S1_coreg_TOPS params
S1C_COH="${S1C_COH:-0.6}"
S1C_FRAC="${S1C_FRAC:-0.02}"
S1C_PHSTD="${S1C_PHSTD:-0.8}"

# EOF download:
# 1 => force ASF bucket (no CDSE login); 0 => use CDSE (needs ~/.netrc)
EOF_FORCE_ASF="${EOF_FORCE_ASF:-1}"

# DEM download (eio elevation):
DEM_MARGIN_DEG="${DEM_MARGIN_DEG:-0.15}"  # expand bounds to be safe
EIO_PRODUCT="${EIO_PRODUCT:-SRTM1}"       # kept for clarity

# GAMMA geoid model (optional)
EGM_GEOID="${EGM_GEOID:-${DIFF_HOME:-}/scripts/egm2008-5.dem}"

# Fine geocoding params
DIFFPAR_WINS="${DIFFPAR_WINS:-32 32}"
DIFFPAR_SRCH="${DIFFPAR_SRCH:-256 256}"
DIFFPAR_OSF="${DIFFPAR_OSF:-6}"

OFFS_NRM="${OFFS_NRM:-128}"
OFFS_NAZ="${OFFS_NAZ:-128}"
OFFS_RSTEP="${OFFS_RSTEP:-64}"
OFFS_ASTEP="${OFFS_ASTEP:-64}"
OFFS_SNR="${OFFS_SNR:-0.15}"
OFFS_ORDER="${OFFS_ORDER:-3}"

############################
# 1) HELPERS
############################
log(){ echo "[$(date +'%F %T')] $*"; }
die(){ echo "ERROR: $*" >&2; exit 1; }
need_cmd(){ command -v "$1" >/dev/null 2>&1 || die "Command not found in PATH: $1"; }
ensure_dir(){ mkdir -p "$1"; }

par_get(){ # par_get file key -> value
  local f="$1" k="$2"
  awk -v key="${k}:" '$1==key {print $2; exit}' "$f"
}

count_nonempty_lines(){
  awk 'NF>0{c++} END{print c+0}'
}

# Choose EOF that covers acquisition time using EOF filename validity window
select_orbit_for_par(){
  local slc_par="$1" orbit_dir="$2"
  python3 - "$slc_par" "$orbit_dir" <<'PY'
import os, re, sys, datetime

slc_par, orbit_dir = sys.argv[1], sys.argv[2]

# read acquisition time
acq = None
for ln in open(slc_par, 'r', errors='ignore'):
  if ln.strip().startswith(('start_time','azimuth_start_time','time_of_first_line','raw_data_start_time','first_line_time')):
    m = re.search(r"(20\d{2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})", ln)
    if m:
      Y,mo,d,H,Mi,S = map(int, m.groups())
      acq = datetime.datetime(Y,mo,d,H,Mi,S)
      break

if acq is None:
  print("")
  raise SystemExit(0)

def parse_valid(fn):
  m = re.search(r"_V(\d{8}T\d{6})_(\d{8}T\d{6})\.EOF$", fn)
  if not m: return None
  fmt = "%Y%m%dT%H%M%S"
  return datetime.datetime.strptime(m.group(1), fmt), datetime.datetime.strptime(m.group(2), fmt)

cands=[]
for fn in os.listdir(orbit_dir):
  if not fn.endswith(".EOF"): continue
  v = parse_valid(fn)
  if not v: continue
  v0,v1 = v
  if v0 <= acq <= v1:
    rank = 0
    if "AUX_POEORB" in fn: rank = 2
    elif "AUX_RESORB" in fn: rank = 1
    cands.append((rank, fn))
if not cands:
  print("")
  raise SystemExit(0)
cands.sort(key=lambda x:(x[0], x[1]))
print(os.path.join(orbit_dir, cands[-1][1]))
PY
}

# Fallback orbit matching by date-1/date+1 in filename
find_orbit_by_date_window(){
  local d="$1" orbit_dir="$2"
  local dm dp
  dm="$(date -d "${d:0:4}-${d:4:2}-${d:6:2} -1 day" +%Y%m%d)"
  dp="$(date -d "${d:0:4}-${d:4:2}-${d:6:2} +1 day" +%Y%m%d)"
  local f
  f="$(ls -1 "${orbit_dir}"/*V"${dm}"T*_"${dp}"T*.EOF 2>/dev/null | tail -n1 || true)"
  echo "$f"
}

# Parse bounds from KML produced by SLC_corners
bounds_from_kml(){
  local kml="$1" margin="$2"
  python3 - "$kml" "$margin" <<'PY'
import re, sys
kml, margin = sys.argv[1], float(sys.argv[2])
txt = open(kml,'r',errors='ignore').read()
coords = re.findall(r"<coordinates>(.*?)</coordinates>", txt, flags=re.S)
pts=[]
for block in coords:
  for tok in block.strip().replace("\n"," ").split():
    parts = tok.split(",")
    if len(parts) >= 2:
      pts.append((float(parts[0]), float(parts[1])))
if not pts:
  raise SystemExit("")
lons=[p[0] for p in pts]; lats=[p[1] for p in pts]
W=min(lons)-margin; E=max(lons)+margin
S=min(lats)-margin; N=max(lats)+margin
print(W, S, E, N)
PY
}

############################
# 2) CHECKS
############################
check_env(){
  need_cmd find; need_cmd sed; need_cmd awk; need_cmd paste; need_cmd sort; need_cmd uniq; need_cmd date; need_cmd python3

  need_cmd eof
  need_cmd eio

  need_cmd S1_TOPS_preproc
  need_cmd SLC_copy_S1_TOPS
  need_cmd S1_OPOD_vec
  need_cmd multi_S1_TOPS
  need_cmd SLC_mosaic_S1_TOPS
  need_cmd SLC_corners
  need_cmd srtm2dem
  need_cmd gc_map
  need_cmd geocode
  need_cmd pixel_area
  need_cmd create_diff_par
  need_cmd init_offsetm
  need_cmd offset_pwrm
  need_cmd offset_fitm
  need_cmd gc_map_fine
  need_cmd multi_look
  need_cmd S1_deramp_TOPS_reference
  need_cmd S1_deramp_TOPS_slave

  if [[ "$COREG_MODE" == "scansar_py" ]]; then
    need_cmd ScanSAR_coreg.py
  else
    need_cmd S1_coreg_TOPS
  fi

  [[ -d "$RAW_DIR" ]] || die "RAW_DIR not found: $RAW_DIR"
}

############################
# 3) PIPELINE
############################
stage_0_prepare(){
  ensure_dir "$WORK_DIR"
  cd "$WORK_DIR"
  log "WORK_DIR=$WORK_DIR"
}

stage_1_safe_list_and_preproc(){
  log "Stage1: safe.list -> S1_TOPS_preproc"
  find "$RAW_DIR" -name manifest.safe > safe_manifest.list
  [[ -s safe_manifest.list ]] || die "No manifest.safe found under RAW_DIR=$RAW_DIR"
  sed -i 's/manifest.safe$//' safe_manifest.list
  cp safe_manifest.list safe.list

  ensure_dir SLC
  S1_TOPS_preproc safe.list SLC "$POL" S1_TOPS_preproc.log
}

stage_2_filter_iw_build_tabs(){
  log "Stage2: filter IWs, build data_tab & *_slc1"
  cd "$WORK_DIR/SLC"

  for iw in 1 2 3; do
    keep=0
    for k in "${IW_KEEP[@]}"; do [[ "$k" == "$iw" ]] && keep=1; done
    if [[ "$keep" -eq 0 ]]; then
      rm -f *_iw${iw}_${POL}.slc *_iw${iw}_${POL}.slc.par *_iw${iw}_${POL}.slc.tops_par *_iw${iw}_${POL}.tops_par 2>/dev/null || true
    fi
  done

  ls -1 *_iw*_"${POL}".slc 2>/dev/null | sed -E "s/_iw[0-9]+_${POL}\.slc$//" | sort -u > data_tab
  [[ -s data_tab ]] || die "data_tab empty. Check S1_TOPS_preproc output / POL / IW selection."

  if [[ -z "${MASTER}" ]]; then
    MASTER="$(head -n 1 data_tab)"
    log "MASTER not set -> auto choose: $MASTER"
  else
    log "MASTER: $MASTER"
  fi
  grep -qx "$MASTER" data_tab || die "MASTER=$MASTER not found in data_tab"

  while read -r d; do
    : > "${d}_1_tab"
    : > "${d}par_1_tab"
    : > "${d}TOPS_par_1_tab"

    for iw in "${IW_KEEP[@]}"; do
      slc="${d}_iw${iw}_${POL}.slc"
      [[ -f "$slc" ]] || die "Missing $slc"
      echo "$slc" >> "${d}_1_tab"
      echo "${slc}.par" >> "${d}par_1_tab"
      if [[ -f "${slc}.tops_par" ]]; then
        echo "${slc}.tops_par" >> "${d}TOPS_par_1_tab"
      elif [[ -f "${d}_iw${iw}_${POL}.tops_par" ]]; then
        echo "${d}_iw${iw}_${POL}.tops_par" >> "${d}TOPS_par_1_tab"
      else
        die "Missing TOPS par for ${slc} (expected *.slc.tops_par or *.tops_par)"
      fi
    done
    paste "${d}_1_tab" "${d}par_1_tab" "${d}TOPS_par_1_tab" > "${d}_slc1"
  done < data_tab
}

stage_3_burst_extract(){
  log "Stage3: burst extraction (SLC_copy_S1_TOPS)"
  cd "$WORK_DIR/SLC"
  ensure_dir burst

  echo -ne "$BURST_TAB_CONTENT\n" > burst/burst_tab
  local need have
  need="${#IW_KEEP[@]}"
  have="$(count_nonempty_lines < burst/burst_tab)"
  [[ "$have" -eq "$need" ]] || die "burst_tab lines ($have) != IW_KEEP count ($need). Fix BURST_TAB_CONTENT."

  while read -r d; do
    awk -v D="$d" '{for(i=1;i<=NF;i++){sub("^"D,"./burst/"D,$i)}; print}' "${d}_slc1" > "burst/${d}_slc2"
  done < data_tab

  cp data_tab burst/
  cp *_slc1 burst/

  while read -r d; do
    SLC_copy_S1_TOPS "./${d}_slc1" "burst/${d}_slc2" "burst/burst_tab" -
  done < data_tab
}

stage_4_download_eof_and_opod(){
  log "Stage4: download EOF by eof + run S1_OPOD_vec"
  cd "$WORK_DIR/SLC/burst"
  ensure_dir orbit

  if [[ "$EOF_FORCE_ASF" == "1" ]]; then
    eof --search-path "$RAW_DIR" --save-dir "$(pwd)/orbit" --force-asf
  else
    eof --search-path "$RAW_DIR" --save-dir "$(pwd)/orbit"
  fi

  while read -r d; do
    for iw in "${IW_KEEP[@]}"; do
      par="./${d}_iw${iw}_${POL}.slc.par"
      [[ -f "$par" ]] || die "Missing $par"
      eof_file="$(select_orbit_for_par "$par" "$(pwd)/orbit" || true)"
      if [[ -z "$eof_file" ]]; then
        eof_file="$(find_orbit_by_date_window "$d" "$(pwd)/orbit" || true)"
      fi
      [[ -n "$eof_file" && -f "$eof_file" ]] || die "Cannot find EOF for date=$d (check eof download / orbit folder)"
      log "S1_OPOD_vec: $d iw${iw} -> $(basename "$eof_file")"
      S1_OPOD_vec "$par" "$eof_file"
    done
  done < data_tab
}

stage_5_mosaic_stack(){
  log "Stage5: mosaic bursts+swaths (multi_S1_TOPS, SLC_mosaic_S1_TOPS)"
  cd "$WORK_DIR/SLC/burst"
  while read -r d; do
    multi_S1_TOPS "${d}_slc1" "${d}.mli" "${d}.mli.par" "$RLKS" "$AZLKS"
    SLC_mosaic_S1_TOPS "${d}_slc1" "${d}.slc" "${d}.slc.par" "$RLKS" "$AZLKS"
  done < data_tab

  [[ -f "${MASTER}.mli.par" ]] || die "Missing master mli.par: ${MASTER}.mli.par (run stage 5 first)"
}

stage_6_dem_auto_download_and_fine_geocode(){
  log "Stage6: DEM auto-download by SLC coverage (SLC_corners + eio clip), then gc_map coarse+fine"
  cd "$WORK_DIR/SLC/burst"
  ensure_dir dem
  ensure_dir DEM

  [[ -f "${MASTER}.mli.par" ]] || die "Missing ${MASTER}.mli.par (Stage6 depends on Stage5)."

  SLC_corners "${MASTER}.mli.par" - "DEM/${MASTER}_corners.kml"
  BOUNDS="$(bounds_from_kml "DEM/${MASTER}_corners.kml" "$DEM_MARGIN_DEG" || true)"
  [[ -n "$BOUNDS" ]] || die "Failed to parse DEM bounds from KML."

  log "DEM bounds (W S E N): $BOUNDS"
  eio clip -o "DEM/dem_${MASTER}.tif" --bounds $BOUNDS

  if [[ -n "$EGM_GEOID" && -f "$EGM_GEOID" ]]; then
    srtm2dem "DEM/dem_${MASTER}.tif" "dem/1.dem" "dem/1.dem.par" 0 "$EGM_GEOID"
  else
    srtm2dem "DEM/dem_${MASTER}.tif" "dem/1.dem" "dem/1.dem.par" 0
  fi

  # IMPORTANT: output dem/inc (and other maps) explicitly
  gc_map "${MASTER}.mli.par" - dem/1.dem.par dem/1.dem \
    dem/seg.dem.par dem/seg.dem dem/lookup_table \
    1 1 dem/sim_sar dem/u dem/v dem/inc dem/psi dem/pix dem/ls_map

  local rs az demw
  rs="$(par_get "${MASTER}.mli.par" range_samples)"
  az="$(par_get "${MASTER}.mli.par" azimuth_lines)"
  demw="$(par_get dem/seg.dem.par width)"
  [[ -n "$rs" && -n "$az" && -n "$demw" ]] || die "Failed reading rs/az/demw from par files."

  pixel_area "${MASTER}.mli.par" dem/seg.dem.par dem/seg.dem \
    dem/lookup_table dem/ls_map dem/inc dem/pix_sigma0 dem/pix_gamma0

  cat > dem/diff_par.in <<EOF

0 0
${DIFFPAR_WINS}
${DIFFPAR_SRCH}
${DIFFPAR_OSF}
EOF
  create_diff_par "${MASTER}.mli.par" - dem/diff_par 1 0 < dem/diff_par.in

  local r0 a0
  r0=$(( rs / 2 ))
  a0=$(( az / 2 ))

  init_offsetm "${MASTER}.mli" dem/pix_sigma0 dem/diff_par 1 1 "$r0" "$a0" - - 0.15 512 || true

  offset_pwrm "${MASTER}.mli" dem/pix_sigma0 dem/diff_par dem/offs dem/ccp \
    "${OFFS_NRM}" "${OFFS_NAZ}" offsets 2 "${OFFS_RSTEP}" "${OFFS_ASTEP}" "${OFFS_SNR}"

  offset_fitm dem/offs dem/ccp dem/diff_par coffs coffsets - "${OFFS_ORDER}"

  gc_map_fine dem/lookup_table "${demw}" dem/diff_par dem/lookup_table_fine 0

  geocode dem/lookup_table_fine dem/seg.dem "${demw}" dem/fine_rdc.seg.dem "${rs}" "${az}" 2 0

  ln -sf "fine_rdc.seg.dem" "dem/${MASTER}.hgt" 2>/dev/null || true
}

stage_7_coreg_to_rslc(){
  log "Stage7: coreg -> RSLC"
  cd "$WORK_DIR/SLC/burst"
  ensure_dir RSLC

  while read -r d; do
    awk -v D="$d" '{for(i=1;i<=NF;i++){sub("^"D,"./RSLC/"D,$i)}; print}' "${d}_slc1" > "${d}_rslc"
  done < data_tab

  SLC_mosaic_S1_TOPS "${MASTER}_slc1" "${MASTER}.rslc" "${MASTER}.rslc.par" "$RLKS" "$AZLKS"
  multi_look "${MASTER}.rslc" "${MASTER}.rslc.par" "${MASTER}.rmli" "${MASTER}.rmli.par" "$RLKS" "$AZLKS"

  cp data_tab data_tab0
  sed -i "/${MASTER}/d" data_tab0

  if [[ "$COREG_MODE" == "scansar_py" ]]; then
    while read -r d; do
      log "ScanSAR_coreg.py: $d"
      if [[ "$SS_NO_INT" == "1" ]]; then
        ScanSAR_coreg.py "${MASTER}_slc1" "${MASTER}" "${d}_slc1" "${d}" "${d}_rslc" \
          dem/fine_rdc.seg.dem "$RLKS" "$AZLKS" \
          --cc "$SS_CC" --fraction "$SS_FRACTION" --ph_stdev "$SS_PHSTD" \
          --nr "$SS_NR" --naz "$SS_NAZ" --rwin "$SS_RWIN" --azwin "$SS_AZWIN" --no_int
      else
        ScanSAR_coreg.py "${MASTER}_slc1" "${MASTER}" "${d}_slc1" "${d}" "${d}_rslc" \
          dem/fine_rdc.seg.dem "$RLKS" "$AZLKS" \
          --cc "$SS_CC" --fraction "$SS_FRACTION" --ph_stdev "$SS_PHSTD" \
          --nr "$SS_NR" --naz "$SS_NAZ" --rwin "$SS_RWIN" --azwin "$SS_AZWIN"
      fi
    done < data_tab0
  else
    while read -r d; do
      log "S1_coreg_TOPS: $d"
      S1_coreg_TOPS "${MASTER}_slc1" "${MASTER}" "${d}_slc1" "${d}" "${d}_rslc" \
        "dem/${MASTER}.hgt" "$RLKS" "$AZLKS" - - "$S1C_COH" "$S1C_FRAC" "$S1C_PHSTD" 1 0
    done < data_tab0
  fi

  ensure_dir coreg_quality
  cp -f *.coreg_quality coreg_quality/ 2>/dev/null || true
}

stage_8_deramp_and_archive(){
  log "Stage8: deramp reference+slaves, archive final SLC stack"
  set +e  # 允许此函数内部命令出错而不终止脚本
  
  cd "$WORK_DIR/SLC/burst"
  
  # 确保RSLC目录存在
  ensure_dir RSLC
  
  # 复制所有必要的原始文件到RSLC目录（关键修复！）
  log "Copying necessary files to RSLC directory..."
  
  # 复制data_tab和slc1文件
  cp -f data_tab *_slc1 RSLC/ 2>/dev/null || true
  
  # 复制master的所有文件
  for iw in "${IW_KEEP[@]}"; do
    # 查找并复制master文件
    for suffix in ".slc" ".slc.par" ".slc.tops_par" ".tops_par"; do
      src_file="${MASTER}_iw${iw}_${POL}${suffix}"
      if [[ -f "$src_file" ]]; then
        cp -f "$src_file" "RSLC/" 2>/dev/null || log "WARN: Could not copy $src_file"
      fi
    done
  done
  
  # 复制所有slave的原始SLC文件（重要！解决找不到文件的问题）
  while read -r d; do
    if [[ "$d" == "$MASTER" ]]; then
      continue  # 跳过master，已经复制过了
    fi
    
    for iw in "${IW_KEEP[@]}"; do
      # 查找并复制slave文件
      for suffix in ".slc" ".slc.par" ".slc.tops_par" ".tops_par"; do
        src_file="${d}_iw${iw}_${POL}${suffix}"
        if [[ -f "$src_file" ]]; then
          cp -f "$src_file" "RSLC/" 2>/dev/null || log "WARN: Could not copy $src_file for slave $d"
        fi
      done
    done
  done < data_tab
  
  cd RSLC
  ensure_dir deramp
  
  # deramp master
  log "Deramping master: $MASTER"
  S1_deramp_TOPS_reference "${MASTER}_slc1" 2>&1 | tee -a deramp_master.log
  
  # 检查master deramp是否成功
  if [[ -f "${MASTER}_slc1.deramp" ]]; then
    SLC_mosaic_S1_TOPS "${MASTER}_slc1.deramp" "${MASTER}.slc" "${MASTER}.slc.par" "$RLKS" "$AZLKS"
    
    # 保存master deramp中间文件
    cp -f "${MASTER}_slc1.deramp"* deramp/ 2>/dev/null || true
    cp -f "${MASTER}.slc" "${MASTER}.slc.par" deramp/ 2>/dev/null || true
    cp -f "${MASTER}_iw"*_"${POL}".slc.deramp* deramp/ 2>/dev/null || true
    log "Master deramp completed successfully"
  else
    log "ERROR: Master deramp failed! Check deramp_master.log for details"
  fi
  
  # 为所有日期创建deramp参数文件
  while read -r d; do
    for iw in "${IW_KEEP[@]}"; do
      # 查找原始参数文件（现在应该在RSLC目录中）
      src_par="${d}_iw${iw}_${POL}.slc.par"
      src_tops1="${d}_iw${iw}_${POL}.slc.tops_par"
      src_tops2="${d}_iw${iw}_${POL}.tops_par"
      
      # 检查文件是否存在
      if [[ ! -f "$src_par" ]]; then
        log "WARN: Parameter file not found in RSLC: $src_par"
        # 尝试从父目录查找
        if [[ -f "../$src_par" ]]; then
          cp -f "../$src_par" "$src_par" 2>/dev/null || log "WARN: Could not copy from parent"
        fi
      fi
      
      # 创建deramp参数文件（如果原始文件存在）
      if [[ -f "$src_par" ]]; then
        cp -f "$src_par" "${d}_iw${iw}_${POL}.slc.deramp.par" 2>/dev/null || true
      fi
      
      # 复制TOPS参数文件
      if [[ -f "$src_tops1" ]]; then
        cp -f "$src_tops1" "${d}_iw${iw}_${POL}.slc.deramp.TOPS_par" 2>/dev/null || true
      elif [[ -f "$src_tops2" ]]; then
        cp -f "$src_tops2" "${d}_iw${iw}_${POL}.slc.deramp.TOPS_par" 2>/dev/null || true
      fi
    done
  done < data_tab
  
  # 创建slave列表（排除master）
  cp data_tab data_tab0
  sed -i "/${MASTER}/d" data_tab0
  
  # deramp slaves
  local slave_count=0
  local slave_success=0
  local slave_failed=()
  
  while read -r d; do
    slave_count=$((slave_count + 1))
    log "Deramping slave $slave_count: $d"
    
    # 检查必要的文件是否存在
    if [[ ! -f "${d}_slc1" ]]; then
      log "ERROR: ${d}_slc1 not found, skipping this slave"
      slave_failed+=("$d")
      continue
    fi
    
    # 运行deramp并记录输出
    log "Running S1_deramp_TOPS_slave for $d"
    S1_deramp_TOPS_slave "${d}_slc1" "$d" "${MASTER}_slc1" "$RLKS" "$AZLKS" - 2>&1 | tee "deramp_${d}.log"
    
    # 检查是否成功
    if [[ -f "${d}.rslc.deramp" && -f "${d}.rslc.deramp.par" ]]; then
      slave_success=$((slave_success + 1))
      # 保存slave deramp输出
      cp -f "${d}.rslc.deramp" "${d}.rslc.deramp.par" deramp/ 2>/dev/null || true
      log "Successfully deramped slave: $d"
    else
      log "WARN: Deramp may have failed for slave: $d (output files not found)"
      slave_failed+=("$d")
    fi
  done < data_tab0
  
  # 归档最终文件到slc目录
  ensure_dir slc
  
  # 归档master
  if [[ -f "${MASTER}.slc" && -f "${MASTER}.slc.par" ]]; then
    mv -f "${MASTER}.slc"     "slc/${MASTER}.slc"
    mv -f "${MASTER}.slc.par" "slc/${MASTER}.slc.par"
    log "Archived master: $MASTER"
  else
    log "WARN: Master output files not found, skipping archive"
  fi
  
  # 归档成功的slaves
  local archived_count=0
  while read -r d; do
    if [[ -f "${d}.rslc.deramp" && -f "${d}.rslc.deramp.par" ]]; then
      mv -f "${d}.rslc.deramp"     "slc/${d}.slc"
      mv -f "${d}.rslc.deramp.par" "slc/${d}.slc.par"
      archived_count=$((archived_count + 1))
      log "Archived slave: $d"
    else
      log "WARN: Slave output files not found for $d, skipping archive"
    fi
  done < data_tab0
  
  log "Deramp summary:"
  log "  Total slaves attempted: $slave_count"
  log "  Successfully deramped: $slave_success"
  log "  Successfully archived: $archived_count"
  
  if (( ${#slave_failed[@]} > 0 )); then
    log "WARN: Failed slaves (will be handled by stage 9): ${slave_failed[*]}"
  fi
  
  log "Deramp backups saved in: $WORK_DIR/SLC/burst/RSLC/deramp/"
  log "Final SLC stack in: $WORK_DIR/SLC/burst/RSLC/slc/"
  
  set -e  # 恢复错误检查模式
}

############################################
# 3.5) STAGE 9 (ONLY ADDITION, OTHERS SAME)
############################################
stage_9_copy_slc_only(){
  log "Stage9: copy/restore ALL YYYYMMDD.slc + YYYYMMDD.slc.par into WORK/SLC/burst/RSLC/slc/ (NO rerun stage8)"
  
  set +e  # 添加：允许此函数内部命令出错而不终止脚本
  
  # go to RSLC
  cd "$WORK_DIR/SLC/burst" || { log "ERROR: Missing burst dir"; exit 1; }
  [[ -d RSLC ]] || { log "ERROR: Missing RSLC dir"; exit 1; }
  cd RSLC

  # decide which data_tab to use (prefer RSLC/data_tab if exists)
  local tab=""
  if [[ -f data_tab ]]; then
    tab="data_tab"
  elif [[ -f ../data_tab ]]; then
    tab="../data_tab"
  else
    log "ERROR: Cannot find data_tab in RSLC or burst"
    exit 1
  fi

  ensure_dir slc

  local total=0 copied=0
  local missing=()

  while read -r d; do
    [[ -n "${d:-}" ]] || continue
    total=$((total+1))

    local dst_slc="slc/${d}.slc"
    local dst_par="slc/${d}.slc.par"

    # 检查是否已经存在（可能是从第8步归档的）
    if [[ -f "$dst_slc" && -f "$dst_par" ]]; then
      log "Already exists: $d"
      continue
    fi

    local src_slc="" src_par=""
    local found_slc=0 found_par=0

    # ---- 查找SLC源文件 ----
    # 优先级1：slc目录（第8步可能已归档）
    if [[ -f "slc/${d}.slc" ]]; then
      src_slc="slc/${d}.slc"
      found_slc=1
    # 优先级2：当前目录的deramp输出
    elif [[ -f "${d}.rslc.deramp" ]]; then
      src_slc="${d}.rslc.deramp"
      found_slc=1
    # 优先级3：deramp目录的备份
    elif [[ -f "deramp/${d}.rslc.deramp" ]]; then
      src_slc="deramp/${d}.rslc.deramp"
      found_slc=1
    # 优先级4：其他可能的位置
    elif [[ -f "${d}.slc" ]]; then
      src_slc="${d}.slc"
      found_slc=1
    elif [[ -f "deramp/${d}.slc" ]]; then
      src_slc="deramp/${d}.slc"
      found_slc=1
    fi

    # ---- 查找PAR源文件 ----
    # 优先级1：slc目录
    if [[ -f "slc/${d}.slc.par" ]]; then
      src_par="slc/${d}.slc.par"
      found_par=1
    # 优先级2：当前目录的deramp输出
    elif [[ -f "${d}.rslc.deramp.par" ]]; then
      src_par="${d}.rslc.deramp.par"
      found_par=1
    # 优先级3：deramp目录的备份
    elif [[ -f "deramp/${d}.rslc.deramp.par" ]]; then
      src_par="deramp/${d}.rslc.deramp.par"
      found_par=1
    # 优先级4：其他可能的位置
    elif [[ -f "${d}.slc.par" ]]; then
      src_par="${d}.slc.par"
      found_par=1
    elif [[ -f "deramp/${d}.slc.par" ]]; then
      src_par="deramp/${d}.slc.par"
      found_par=1
    fi

    # 复制找到的文件
    if [[ $found_slc -eq 1 ]]; then
      cp -f "$src_slc" "$dst_slc" 2>/dev/null && log "Copied SLC for $d"
    fi
    if [[ $found_par -eq 1 ]]; then
      cp -f "$src_par" "$dst_par" 2>/dev/null && log "Copied PAR for $d"
    fi

    # 验证结果
    if [[ -f "$dst_slc" && -f "$dst_par" ]]; then
      copied=$((copied+1))
    else
      # 清理不完整的文件
      [[ -f "$dst_slc" && ! -f "$dst_par" ]] && rm -f "$dst_slc"
      [[ -f "$dst_par" && ! -f "$dst_slc" ]] && rm -f "$dst_par"
      missing+=("$d")
      log "WARN: Incomplete files for $d (SLC: $found_slc, PAR: $found_par)"
    fi
  done < "$tab"

  local n_slc n_par
  n_slc="$(ls -1 slc/*.slc 2>/dev/null | wc -l || echo 0)"
  n_par="$(ls -1 slc/*.slc.par 2>/dev/null | wc -l || echo 0)"
  
  log "Stage9 summary:"
  log "  Dates in data_tab: $total"
  log "  Successfully copied: $copied"
  log "  SLC files in slc/: $n_slc"
  log "  PAR files in slc/: $n_par"

  if (( ${#missing[@]} > 0 )); then
    log "WARN: Missing dates (need manual processing): ${missing[*]}"
  fi
  
  set -e  # 恢复错误检查
}

############################
# 4) DRIVER (single stage OR range)
############################
usage(){
  cat <<EOF
Usage:
  $0 all
  $0 N                 # run single stage N (1..9)
  $0 START END         # run stages START..END (inclusive), e.g. 6 9
  $0 START-END         # same as above, e.g. 6-9

Stages:
  1 safe.list + S1_TOPS_preproc
  2 IW filter + data_tab + *_slc1
  3 burst extract
  4 eof download + S1_OPOD_vec
  5 mosaic stack
  6 DEM auto download + fine geocoding
  7 coreg to RSLC
  8 deramp + archive slc (PREPROCESSING OVER)
  9 copy slc outputs into RSLC/slc/ (copy-only, no other side effects)
EOF
}

is_int(){ [[ "${1:-}" =~ ^[0-9]+$ ]]; }

run_stage(){
  local s="$1"
  case "$s" in
    1) stage_1_safe_list_and_preproc ;;
    2) stage_2_filter_iw_build_tabs ;;
    3) stage_3_burst_extract ;;
    4) stage_4_download_eof_and_opod ;;
    5) stage_5_mosaic_stack ;;
    6) stage_6_dem_auto_download_and_fine_geocode ;;
    7) stage_7_coreg_to_rslc ;;
    8) stage_8_deramp_and_archive ;;
    9) stage_9_copy_slc_only ;;   # <-- ONLY ADDITION
    *) die "Invalid stage: $s (must be 1..9)" ;;
  esac
}

infer_master_if_empty(){
  if [[ -z "${MASTER:-}" ]]; then
    if [[ -f "$WORK_DIR/SLC/burst/data_tab" ]]; then
      MASTER="$(head -n 1 "$WORK_DIR/SLC/burst/data_tab")"
      log "MASTER was empty -> infer from burst/data_tab: $MASTER"
    elif [[ -f "$WORK_DIR/SLC/data_tab" ]]; then
      MASTER="$(head -n 1 "$WORK_DIR/SLC/data_tab")"
      log "MASTER was empty -> infer from SLC/data_tab: $MASTER"
    fi
  fi
}

run_range(){
  local start="$1" end="$2"
  is_int "$start" && is_int "$end" || die "START/END must be integers"
  (( start>=1 && start<=9 )) || die "START must be 1..9"
  (( end>=1 && end<=9 )) || die "END must be 1..9"
  (( start<=end )) || die "START must be <= END"

  if (( start>=5 )); then
    infer_master_if_empty
  fi

  local s
  for s in $(seq "$start" "$end"); do
    log "Starting stage $s..."
    # 临时关闭错误检查，确保即使某一步失败也能继续
    set +e
    run_stage "$s"
    local stage_status=$?
    set -e
    
    if [[ $stage_status -ne 0 ]]; then
      log "WARNING: Stage $s returned non-zero exit status ($stage_status), but continuing..."
    else
      log "Stage $s completed successfully"
    fi
  done
}

main(){
  # ===== 作者信息 =====
  echo ""
  echo "================================================================="
  echo "  GAMMA Sentinel-1 TOPS Pre-Processing Script"
  echo "  Author: Shuai Wang"
  echo "  Affiliation: China University of Mining and Technology"
  echo "  Time: 2026/01/01"
  echo "================================================================="
  echo ""
  
  check_env
  stage_0_prepare

  local a="${1:-all}"
  local b="${2:-}"

  if [[ "$a" == "all" ]]; then
    # 运行1-9阶段，但第8步内部有容错处理
    run_range 1 9
    exit 0
  fi

  if [[ "$a" =~ ^([0-9]+)-([0-9]+)$ ]]; then
    run_range "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}"
    exit 0
  fi

  if is_int "$a" && is_int "$b"; then
    run_range "$a" "$b"
    exit 0
  fi

  if is_int "$a" && [[ -z "$b" ]]; then
    if (( a>=5 )); then
      infer_master_if_empty
    fi
    run_stage "$a"
    exit 0
  fi

  usage
  exit 1
}

main "$@"
