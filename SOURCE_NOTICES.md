# Public source notices

## GeoNames

Source: [GeoNames](https://www.geonames.org/) and its [downloadable gazetteer](https://download.geonames.org/export/dump/).

The GeoNames extract is licensed under [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/). The source [readme](https://download.geonames.org/export/dump/readme.txt) identifies this license and states that the data is supplied without assurances of accuracy, timeliness or completeness. Commercial reuse is allowed subject to attribution and the license terms.

Contifield's changes: select populated-place feature classes and fields; preserve source native and ASCII names, coordinates and identifiers; exclude explicitly historical, abandoned and destroyed classes; validate geometry and row shape; normalize search keys; sort and partition data into static shards. No population threshold is applied. Names and source classifications are not endorsements or statements about sovereignty. The full original extract is retained as a separate versioned release asset for reproducibility.

Redistributions of this derived catalog must retain credit to GeoNames, a license link and a description of modifications. The application must show attribution in the location interface and source documentation.

## IANA timezone data and compiler

Source: [IANA Time Zone Database release 2026e](https://www.iana.org/time-zones/releases/2026e), including the pinned data and code archives listed in the source lock.

The IANA distribution LICENSE states that its code and data are in the public domain except designated BSD-derived files (`date.c`, `newstrftime.3` and `strftime.c`) when present. Those files are not used to generate or distributed inside the derived timezone JSON. Original archives preserve their own notices.

Contifield compiles the pinned `zic` source and extracts UTC offset transitions for a finite planning window with guard days. The derived JSON includes canonical zone names, source aliases, rule edition and source/compiler hashes. Abbreviations and legal certainty about future government decisions are not inferred. IANA's geographic naming and country table do not endorse territorial claims.

No private application information or visitor data is included in this repository or the generated release.
