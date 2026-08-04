# Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [1.2.0]

- Adding new APIs to for making it easier to write tests / scripts for Kit-CAE.
  Introduced `get_vtrt_array_as_numpy`, `wait_for_update`, `frame_prims`, `new_stage`.
- Tightened test harness synchronization to reliably wait for CAE viz operator execution and
  fabric stage updates, eliminating flakiness in operator-stack integration tests.


## [1.0.0]

- Initial version.
