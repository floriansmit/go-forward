# Facies Configuration System

The GO-Forward dashboard now supports universal, dynamic facies configuration. This allows you and TNO to use different GRDECL files with different facies codes without modifying the code.

## How It Works

### 1. **Facies Configuration File** (`facies_config.json`)

Located in the dashboard folder, this JSON file maps facies codes to colors:

```json
{
  "facies_colors": {
    "0": "#d3d3d3",
    "1": "#4e79a7",
    "2": "#2bd1f2",
    "3": "#e4e1bf",
    "4": "#59a14f",
    "5": "#ed4854",
    "6": "#d08d2c",
    "7": "#9c755f",
    "8": "#b07aa1",
    "9": "#ff9da7"
  }
}
```

### 2. **Automatic Facies Detection**

The dashboard automatically detects when a property column contains discrete facies values by checking:
- Column name matches `FACIES`, `FACIE`, or `FACIESID` (case-insensitive)
- Values are all integers
- The dataset has reasonable facies count

### 3. **Interactive Color Customization**

When viewing facies in the map or cross-section viewers:

1. **Select a facies property** from the "Property" dropdown
2. **Color picker panel appears** showing all detected facies codes
3. **Adjust colors** using the color pickers
4. **Save current colors** - button persists your colors to `facies_config.json`
5. **Reset to defaults** - restores the default color palette
6. **Download JSON** - export the current palette for sharing or backup

### 4. **Discrete Color Scales**

Facies now display with:
- **Discrete colors** (not continuous gradients)
- **Color name in legend** (e.g., "Facies 1", "Facies 2")
- **Consistent colors** across all viewers (map and cross-section)

## Using Different Facies Codes

### For Your Own GRDECLs

Simply update `facies_config.json` with your facies codes and preferred colors:

```json
{
  "facies_colors": {
    "100": "#FF0000",
    "200": "#00FF00",
    "300": "#0000FF"
  }
}
```

The dashboard will:
- Automatically detect these codes in your GRDECL files
- Display them with the specified colors
- Allow interactive adjustment

### For TNO or External Users

1. **Extract the current palette** from the dashboard:
   - View any facies property
   - Click "Download JSON" button
   - This exports `facies_colors.json`

2. **Share the configuration**:
   - Send `facies_config.json` to TNO
   - They place it in their dashboard folder
   - It automatically loads their facies scheme

3. **Or upload their configuration**:
   - Receive their `facies_config.json`
   - Replace the file in your dashboard folder
   - Restart the dashboard

## Example Workflow

### Scenario: TNO sends you a GRDECL with custom facies codes (1000, 2000, 3000)

1. They provide their `facies_config.json`:
   ```json
   {
     "facies_colors": {
       "1000": "#AA3333",
       "2000": "#33AA33",
       "3000": "#3333AA"
     }
   }
   ```

2. Replace the `facies_config.json` in your dashboard folder

3. Load your GRDECL in the dashboard

4. When you select "Facies" property, the dashboard auto-detects codes 1000, 2000, 3000

5. Color pickers appear for each facies with their predefined colors

## Technical Details

- **Colors are stored in**: `dashboard/facies_config.json`
- **Colors are updated in**: Session state and JSON file (when you click Save)
- **Facies detection**: Automatic based on column name and integer values
- **Default palette**: 20 predefined colors used if facies not in config
- **Persistence**: Colors persist across dashboard restarts (stored in JSON)

## Troubleshooting

### Facies not showing in discrete colors?
- Check that the column name is exactly "Facies", "FACIES", or "FACIESID"
- Ensure all values are integers (no NaN or float values)
- Restart the dashboard: `Ctrl+C`, then `python workflow.py dashboard` (`.\run_dashboard.ps1` on Windows)

### Can't find color picker?
- Make sure you selected a facies property from the "Property" dropdown
- The color picker panel only appears for detected facies columns

### Want to reset to defaults?
- Click "Reset to defaults" button in the color picker panel
- Or delete `facies_config.json` and restart dashboard

## API Reference

### Configuration Functions

```python
# Read current facies colors
palette = read_facies_config()
# Returns: {1: "#4e79a7", 2: "#2bd1f2", ...}

# Write new colors
write_facies_config({1: "#FF0000", 2: "#00FF00"})
# Saves to facies_config.json and shows success message

# Check if property is facies
is_discrete = is_discrete_facies_property("Facies", values)
# Returns: True if column is detected as discrete facies

# Get facies codes present in data
categories = get_visible_facies(values)
# Returns: [1, 2, 5, 8] (sorted list of unique facies)

# Get color picker UI
colors = facies_color_settings(categories, key_prefix)
# Returns: {1: "#4e79a7", 2: "#2bd1f2", ...}
```

## Future Enhancements

Possible improvements:
- Import facies legend from GRDECL headers
- Support for facies names (e.g., "Shale", "Sandstone")
- Batch color assignment by facies range
- Color theme presets (by depositional system, etc.)
