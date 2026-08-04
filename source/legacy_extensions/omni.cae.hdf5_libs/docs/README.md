# HDF5 Libraries Extension (omni.cae.hdf5_libs)

This legacy compatibility extension provides HDF5 library support for the retired
CGNS, HDF5, and EDEM data delegates. Active file-format support uses `omni.cae.usd_plugins`.

## Dependencies

This extension manages the following HDF5 libraries:
- libhdf5
- libhdf5_cpp
- libhdf5_hl
- libhdf5_hl_cpp

## Platform Support

- Windows: Links against hdf5.dll, hdf5_cpp.dll, hdf5_hl.dll
- Linux: Links against shared libraries (.so files)
