<#
.SYNOPSIS
Rebuilds the synthetic demonstration outputs from source GRDECL models.

.DESCRIPTION
Runs any or all of the Best-fit, Union, Control, and Uber workflows, including
the local synthetic T>Map-property generator.  It is intended to recreate the
example outputs in this repository; it does not replace a real T>Map run.

.EXAMPLE
.\regenerate_synthetic_outputs.ps1

.EXAMPLE
.\regenerate_synthetic_outputs.ps1 -Approach Control -FaciesProperty FACIES
#>
[CmdletBinding()]
param(
    [string]$SourceDir,
    [string]$FaciesProperty = "Facies",
    [string]$FaciesConfig,
    [ValidateSet("All", "BestFit", "Union", "Control", "Uber")]
    [string]$Approach = "All",
    [ValidateSet("all", "reservoir_quality")]
    [string]$PropertyProfile = "reservoir_quality",
    [int]$ControlVerticalSpacing = 50,
    [string]$UberVerticalSpacing = "25"
)

$ErrorActionPreference = "Stop"

# $PSScriptRoot is populated only after PowerShell has evaluated the parameter
# block, so resolve script-relative defaults here rather than in param().
if ([string]::IsNullOrWhiteSpace($SourceDir)) {
    $SourceDir = Join-Path $PSScriptRoot "input\source_grdecls_from_dionisosflow"
}
if ([string]::IsNullOrWhiteSpace($FaciesConfig)) {
    $SourceConfig = Join-Path $SourceDir "facies_config.json"
    $FaciesConfig = if (Test-Path -LiteralPath $SourceConfig) {
        $SourceConfig
    } else {
        Join-Path $PSScriptRoot "dashboard\facies_config.json"
    }
}

$Python = "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = "python"
}

if (-not (Test-Path -LiteralPath $SourceDir)) {
    throw "Source GRDECL directory was not found: $SourceDir"
}
if (-not (Test-Path -LiteralPath $FaciesConfig)) {
    throw "Facies configuration was not found: $FaciesConfig"
}
if (-not (Get-ChildItem -LiteralPath $SourceDir -File | Where-Object { $_.Extension -ieq ".grdecl" })) {
    throw "No .grdecl files were found in: $SourceDir"
}

function Invoke-WorkflowPython {
    param([Parameter(Mandatory = $true)][string[]]$Command)

    & $Python @Command
    if ($LASTEXITCODE -ne 0) {
        throw "Workflow command failed: $Python $($Command -join ' ')"
    }
}

$Outputs = Join-Path $PSScriptRoot "outputs"

if ($Approach -eq "All" -or $Approach -eq "BestFit") {
    Write-Host "`n=== Best-fit ===" -ForegroundColor Cyan
    $Root = Join-Path $Outputs "Best-fit approach"
    Invoke-WorkflowPython @("scripts\build_best_fit_grdecl_to_pointset.py", "--grdecl-dir", $SourceDir, "--output-dir", (Join-Path $Root "01_3d_points_from_original_grdecls"), "--property", $FaciesProperty)
    Invoke-WorkflowPython @("scripts\generate_synthetic_tmap_data.py", "--source-dir", (Join-Path $Root "01_3d_points_from_original_grdecls"), "--output-dir", (Join-Path $Root "02_3d_points_with_tmap_data"), "--glob", "*_3d_pointset", "--property-profile", $PropertyProfile)
    Invoke-WorkflowPython @("scripts\append_best_fit_tmap_to_grdecls.py", "--grdecl-dir", $SourceDir, "--pointset-dir", (Join-Path $Root "02_3d_points_with_tmap_data"), "--output-dir", (Join-Path $Root "03_augmented_grdecls_with_tmap_data"))
}

if ($Approach -eq "All" -or $Approach -eq "Union") {
    Write-Host "`n=== Multi-realization Union ===" -ForegroundColor Cyan
    $Root = Join-Path $Outputs "Multi-realization union approach"
    Invoke-WorkflowPython @("scripts\build_multi_realizations_grdecls_to_union_pointsets.py", "--grdecl-dir", $SourceDir, "--output-dir", (Join-Path $Root "01_union_pointsets_by_facies"), "--property", $FaciesProperty, "--facies-config", $FaciesConfig, "--tmap-enabled-only")
    Invoke-WorkflowPython @("scripts\generate_synthetic_tmap_data.py", "--source-dir", (Join-Path $Root "01_union_pointsets_by_facies"), "--output-dir", (Join-Path $Root "02_union_pointsets_with_tmap_data"), "--glob", "union_facies_*", "--property-profile", $PropertyProfile)
    Invoke-WorkflowPython @("scripts\append_multi_realizations_union_tmap_to_grdecls.py", "--grdecl-dir", $SourceDir, "--pointset-dir", (Join-Path $Root "02_union_pointsets_with_tmap_data"), "--output-dir", (Join-Path $Root "03_augmented_grdecls_from_union_lookup"))
}

if ($Approach -eq "All" -or $Approach -eq "Control") {
    Write-Host "`n=== Multi-realization Control ===" -ForegroundColor Cyan
    $Root = Join-Path $Outputs "Multi-realization control approach"
    Invoke-WorkflowPython @("scripts\build_multi_realizations_grdecls_to_control_pointsets.py", "--grdecl-dir", $SourceDir, "--output-dir", (Join-Path $Root "01_control_pointsets_by_facies"), "--property", $FaciesProperty, "--max-vertical-spacing", $ControlVerticalSpacing, "--facies-config", $FaciesConfig, "--tmap-enabled-only")
    Invoke-WorkflowPython @("scripts\generate_synthetic_tmap_data.py", "--source-dir", (Join-Path $Root "01_control_pointsets_by_facies"), "--output-dir", (Join-Path $Root "02_control_pointsets_with_tmap_data"), "--glob", "control_facies_*", "--property-profile", $PropertyProfile)
    Invoke-WorkflowPython @("scripts\append_multi_realizations_control_tmap_to_grdecls.py", "--grdecl-dir", $SourceDir, "--pointset-dir", (Join-Path $Root "02_control_pointsets_with_tmap_data"), "--output-dir", (Join-Path $Root "03_augmented_grdecls_from_control_interpolation"), "--property", $FaciesProperty)
}

if ($Approach -eq "All" -or $Approach -eq "Uber") {
    Write-Host "`n=== Multi-realization Uber ===" -ForegroundColor Cyan
    $Root = Join-Path $Outputs "Multi-realization Uber approach"
    Invoke-WorkflowPython @("scripts\build_multi_realizations_grdecls_to_uber_pointsets.py", "--grdecl-dir", $SourceDir, "--output-dir", (Join-Path $Root "01_uber_pointsets_by_facies"), "--property", $FaciesProperty, "--vertical-spacing", $UberVerticalSpacing, "--facies-config", $FaciesConfig, "--tmap-enabled-only")
    Invoke-WorkflowPython @("scripts\generate_synthetic_tmap_data.py", "--source-dir", (Join-Path $Root "01_uber_pointsets_by_facies"), "--output-dir", (Join-Path $Root "02_uber_pointsets_with_tmap_data"), "--glob", "uber_facies_*", "--property-profile", $PropertyProfile)
    Invoke-WorkflowPython @("scripts\append_multi_realizations_uber_tmap_to_grdecls.py", "--grdecl-dir", $SourceDir, "--pointset-dir", (Join-Path $Root "02_uber_pointsets_with_tmap_data"), "--output-dir", (Join-Path $Root "03_augmented_grdecls_from_uber_lookup"), "--property", $FaciesProperty)
    Invoke-WorkflowPython @("scripts\write_petrel_standard_uber_grdecls.py", "--grdecl-dir", $SourceDir, "--pointset-dir", (Join-Path $Root "02_uber_pointsets_with_tmap_data"), "--output-dir", (Join-Path $Root "04_petrel_standard_grdecls_from_uber_lookup"))
}

Write-Host "`nCompleted synthetic output generation." -ForegroundColor Green
