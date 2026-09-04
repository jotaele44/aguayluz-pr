# AguaYLuz map-manifestation coordinate binding v0.3

This contract binds the map's observed coordinate source without promoting a
rendered point into canonical feature identity.

| Existing map path | Receipt method | Canonicality |
|---|---|---|
| direct event `lat/lon` | source-specific direct method, default `SOURCE_REPORTED` | source-native observation; not shared reference geometry |
| first linked asset | `LINKED_ASSET` | derived reference link; exact upstream release pin required |
| municipality asset average | `DERIVED_AVERAGE` | noncanonical display derivation |
| no valid coordinate | `UNKNOWN` / `NULL_EMPTY` | not rendered |

`MAP_MANIFESTATION_OWNER` is always AguaYLuz. `DOMAIN_AUTHORITY` is AguaYLuz.
`GEOMETRY_AUTHORITY` is inherited from the source or linked-asset geometry; an
asset average has none. Every receipt fixes `identity_effect = NONE`.

This closes the coordinate-provenance contract. Wiring the receipt into every
`AssetMap.eventFeatureCollection` emission remains a discrete frontend change
and must preserve the current event-count and no-silent-synthesis regressions.
