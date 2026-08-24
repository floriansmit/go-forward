# Project classification definitions

Each project stores its classification definition beside the source GRDECLs:

```text
input/<project>/source_grdecls/facies_config.json
```

The JSON field names retain `facies_*` for backwards compatibility, but the dashboard presents them according to the project profile:

- **MVP and Siliciclastics:** Facies
- **Carbonates:** Carbonate facies
- **Crystalline rocks:** Rock type

## Create or edit definitions

In the first relevant dashboard tab, select the integer classification property first. Then open **Facies definitions** or **Rock type definitions**. The editor reads all integer codes present in the selected GRDECL and lets you set a name and colour for each.

MVP and siliciclastic projects additionally expose the **T>Map** switch. Disable it for non-reservoir classes that should not be exported to T>Map. Carbonate and crystalline profiles deliberately do not show this switch.

Definitions are saved immediately to the selected project's `facies_config.json`, not to the global dashboard folder.

## JSON structure

```json
{
  "facies_property": "RockType",
  "source_grdecl_files": ["crystalline_pluton_demo.grdecl"],
  "facies_names": {
    "1": "Granite pluton",
    "2": "Contact metamorphic aureole"
  },
  "facies_colors": {
    "1": "#d73027",
    "2": "#fc8d59"
  },
  "facies_metadata": {
    "1": {"category": "reservoir"}
  }
}
```

For a siliciclastic/MVP project, metadata can include the T>Map export rule:

```json
"facies_metadata": {
  "3": {"category": "reservoir", "tmap_enabled": true},
  "10": {"category": "non_reservoir", "tmap_enabled": false}
}
```

The viewers recognise `Facies`, `RockType`, `Lithology`, and common uppercase/underscore variants as discrete integer classifications. If a new source model reuses a code with a different geological meaning, create a separate project rather than reusing its definition file.
