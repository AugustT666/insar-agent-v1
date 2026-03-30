import os
import h5py
import argparse
import numpy as np
from osgeo import gdal

'''
公众号： SAR&InSAR
2026.1.30
'''
# Disable GDAL exceptions to handle errors via return codes
gdal.UseExceptions()

def create_insar_color_table(mode="general"):
    """
    Creates specialized InSAR color tables.
    mode="phase":     Cyclic rainbow (Red-Yellow-Green-Cyan-Blue-Magenta-Red).
    mode="coherence": Linear Black-to-White ramp (0 to 1).
    mode="general":   Standard Rainbow/Jet ramp for continuous real values.
    """
    colors = gdal.ColorTable()
    
    if mode == "phase":
        # Cyclic colors for wrapped data (ends meet at Red)
        nodes = [(255, 0, 0), (255, 255, 0), (0, 255, 0), (0, 255, 255), 
                 (0, 0, 255), (255, 0, 255), (255, 0, 0)]
    elif mode == "coherence":
        # Grayscale ramp for coherence quality
        nodes = [(0, 0, 0), (255, 255, 255)]
    else:
        # Standard Rainbow (Jet style) for real numbers like Unwrapped Phase
        nodes = [(0, 0, 128), (0, 0, 255), (0, 255, 255), (0, 255, 0), 
                 (255, 255, 0), (255, 0, 0), (128, 0, 0)]

    n_nodes = len(nodes)
    for i in range(256):
        f = i / 255.0
        idx = f * (n_nodes - 1)
        lower = int(np.floor(idx))
        upper = int(np.ceil(idx))
        dist = idx - lower
        r = int(nodes[lower][0] * (1 - dist) + nodes[upper][0] * dist)
        g = int(nodes[lower][1] * (1 - dist) + nodes[upper][1] * dist)
        b = int(nodes[lower][2] * (1 - dist) + nodes[upper][2] * dist)
        colors.SetColorEntry(i, (r, g, b, 255))
        
    return colors

def convert_h5_to_geotiff(input_h5, output_dir):
    print(f"Scanning NISAR H5 file: {input_h5} ...")
    
    # Setup directories
    browse_dir = os.path.join(output_dir, "browse")
    if not os.path.exists(browse_dir):
        os.makedirs(browse_dir, exist_ok=True)

    with h5py.File(input_h5, 'r') as f:
        def visitor(name, obj):
            if isinstance(obj, h5py.Dataset):
                # Skip non-spatial data (scalars, 1D arrays, and metadata strings)
                shape = obj.shape
                if len(shape) < 2: 
                    return

                # Generate clean filenames from H5 paths
                clean_name = name.replace('/', '_').strip('_')
                tif_path = os.path.join(output_dir, f"{clean_name}.tif")
                png_path = os.path.join(browse_dir, f"{clean_name}.png")

                # Detect complex data (requires phase extraction)
                is_complex = np.issubdtype(obj.dtype, np.complexfloating)
                
                # Source path for GDAL
                if is_complex:
                    gdal_src = f'DERIVED_SUBDATASET:PHASE:NETCDF:"{input_h5}":/{name}'
                else:
                    gdal_src = f'NETCDF:"{input_h5}":/{name}'

                try:
                    # 1. Generate full-resolution GeoTIFF
                    ds_raw = gdal.Translate(tif_path, gdal_src, format='GTiff')
                    
                    if ds_raw is not None:
                        band = ds_raw.GetRasterBand(1)
                        lower_name = name.lower()
                        
                        # --- Logic fix: Identify colormap mode ---
                        # Priority 1: Check for Coherence
                        if "coherencemagnitude" in lower_name:
                            mode = "coherence"
                            scale_min, scale_max = 0.0, 1.0
                        
                        # Priority 2: Check for Wrapped Phase (requires cyclic color)
                        elif "wrappedinterferogram" in lower_name:
                            mode = "phase"
                            scale_min, scale_max = -3.1416, 3.1416
                        
                        # Priority 3: Check for Unwrapped Phase (Real numbers, use general ramp)
                        elif "unwrappedphase" in lower_name:
                            mode = "general"
                            stats = band.GetStatistics(True, True)
                            scale_min, scale_max = stats[0], stats[1]
                        
                        # Fallback for other phase-related items (ionosphere etc.)
                        elif "phase" in lower_name:
                            mode = "phase"
                            scale_min, scale_max = -3.1416, 3.1416
                        
                        # Default for everything else (Masks, offsets, etc.)
                        else:
                            mode = "general"
                            stats = band.GetStatistics(True, True)
                            scale_min, scale_max = stats[0], stats[1]

                        # 2. Generate Browse PNG with correct colormap
                        # Rescale to Byte (0-255) in memory
                        mem_ds = gdal.Translate('', ds_raw, format='MEM', 
                                              outputType=gdal.GDT_Byte, 
                                              scaleParams=[[scale_min, scale_max, 0, 255]],
                                              bandList=[1])
                        
                        # Apply the selected color table
                        mem_ds.GetRasterBand(1).SetColorTable(create_insar_color_table(mode))
                        
                        # Save to PNG file
                        gdal.Translate(png_path, mem_ds, format='PNG')
                        
                        print(f"  [Success] {name} -> Mode: {mode}")
                        
                        # Cleanup
                        mem_ds = None
                        ds_raw = None 
                except Exception as e:
                    print(f"  [Skipped] {name}: {str(e)[:100]}")

        # Recursively visit all items in H5
        f.visititems(visitor)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Full NISAR GUNW to GeoTIFF/PNG Converter")
    parser.add_argument("-i", "--input", required=True, help="Input NISAR H5 file path")
    parser.add_argument("-o", "--output", default="geotiff_results", help="Output directory")
    
    args = parser.parse_args()
    
    # Ensure output directory exists
    if not os.path.exists(args.output):
        os.makedirs(args.output, exist_ok=True)
        
    convert_h5_to_geotiff(args.input, args.output)
    print("\nAll tasks completed successfully.")