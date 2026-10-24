# Contifield open geographic data

This public, data-only repository processes openly licensed geographic inputs. It contains no private application code, user records, analytics configuration, credentials or account data.

The builder pins GeoNames' 24 October 2026 extract and IANA timezone data/compiler 2026e by byte count and SHA-256. It produces a reusable country registry, finite timezone transitions and a static search catalog for source-listed cities, villages and populated localities. Searchable coverage does not create millions of indexable web pages or establish Google demand or ranking probabilities.

## Publish the first edition

Run the **Publish pinned public world data** GitHub Actions workflow manually. It uses the repository's built-in `GITHUB_TOKEN` with `contents: write`, restricted to this data-only repository. It needs no new secret or paid API. The workflow creates a versioned GitHub release; it never replaces an existing release or changes repository access.

The release includes the compact combined archive, build receipt, source/derived hashes and licensing notice. It also preserves the five pinned original public source inputs, because the daily GeoNames URLs are overwritten. Release assets are the durable inputs. CI caches are optional accelerators and are not treated as archives.

The reviewed first-edition bundle is `contifield-world-data.tar.gz`, 151,253,940 bytes, SHA-256 `4f1ad4825d6fdc5f6d55395adec07a6b6b11b6cb33b5e4ad7e38fe9cba97067d`. It includes 5,170,289 populated-place records in 6,196 static assets, the 250-entry geographic registry and 597 IANA zone names/aliases. The complete expected archive, manifest and generated-file hashes are pinned in `data/world-sources.lock.json`. A pin describes the required release; it does not establish that the release has been published.

The first-publication workflow verifies both the original source hashes and the rebuilt archive against this reviewed pin. If a daily upstream has changed, a source is unavailable or the rebuilt archive differs, publication stops. It never substitutes a current extract, changes the pin automatically or overwrites an existing edition. Compression-library changes can alter archive bytes even when the underlying JSON matches; such an output needs review. A previously verified copy of the exact pinned bundle and its five pinned original source inputs can instead be uploaded to the new release by an authorized release operator. The original places-only archive is not compatible with the combined-bundle installer.

A normal application build downloads the exact release URL in the published `world-sources.lock.json`, verifies the archive hash and all asset hashes, and installs the generated JSON and static assets. It never downloads the worldwide raw source at request time or sends a visitor's query to GeoNames.

## Data and coverage

- The registry has 249 ISO 3166-1 country/area codes plus the separately identified GeoNames code XK. Obsolete AN and CS provider records are excluded. Classifications do not imply a position on sovereignty.
- Populated places have no minimum population threshold. The builder preserves source native/ASCII names, IDs, WGS84 coordinates, region identifiers, timezone IDs and modification dates. It does not assume region identifiers are ASCII ISO codes.
- Explicitly historical, abandoned and destroyed feature classes are excluded. Malformed records are counted. Missing/unrecognized timezones remain null; no country-wide offset is invented.
- A country may have no populated-place entries. The catalog is not a claim that every real-world settlement is recorded or current. Source primary and ASCII names are searchable; the separate alternate-name database is not included.
- Time conversion uses pinned IANA rules for local planning dates in 2020–2035, with guard days for UTC rollover. It does not depend on a visitor's browser timezone database. Future legal changes require a new data edition.

## Rebuild and update

The script uses Python's standard library, a C compiler and `make`. It compiles the pinned IANA `zic` source and streams the GeoNames ZIP into a temporary disk-backed SQLite database. It emits country/region name-index shards of at most 512 KiB. The dataset is never held in a Worker heap.

```sh
python3 scripts/build-world-data.py --download \
  --source-dir /tmp/world-inputs --base-output /tmp/world-generated \
  --places-output /tmp/world-places \
  --archive-output /tmp/contifield-world-data.tar.gz \
  --receipt-output /tmp/build-receipt.json
```

For a later rebuild of the same edition, add `--mirror-base https://github.com/ramatladi/contifield-open-data/releases/download/geonames-2026-10-24-v1`; the checksummed release copies are tried before the original URLs. An unavailable or mismatched source fails the build. It does not silently substitute a newer extract or publish an empty catalog.

## Application installation

After the public release is verified, an application build installs the pinned combined bundle with:

```sh
python3 scripts/build-world-data.py --lock data/world-sources.lock.json \
  --source-dir /tmp/contifield-world-cache \
  --install-output public/assets/world-places --base-output src/data
```

The installer verifies the archive SHA-256 before extraction, rejects unsafe paths and unexpected files, verifies the bundle manifest, both generated metadata files and every country manifest/place shard, then installs the static assets. It fails when the release is unavailable or differs. Keep the generated `public/assets/world-places/` tree out of application source control; it is a build output. No visitor request fetches a GeoNames source or GitHub archive.

For a new edition, review the new source hashes, update the lock and dataset ID, run the data checks, then publish a new release. Do not overwrite a prior edition. Application deployment uses a reviewed archive pin and remains separate.

See [SOURCE_NOTICES.md](SOURCE_NOTICES.md) for attribution and reuse terms.
