# Geocosm T>Map point-set hand-off

## Input columns — retain exactly

The first five output columns must remain in this order and retain their values exactly:

```text
X
Y
Z
INT,Facies
INT,CellIndex
```

`CellIndex` is zero-based and identifies the corresponding cell in the supplied GRDECL. Do not replace it with a T>Map-generated `point_id`.

## Requested T>Map output columns

Append the following columns after `CellIndex`, in this order, for PyThermogis-compatible porosity and permeability uncertainty summaries:

```text
FLOAT,total_porosity_mean
FLOAT,total_porosity_stdev
FLOAT,total_porosity_p10
FLOAT,total_porosity_p50
FLOAT,total_porosity_p90
FLOAT,permeability_mean
FLOAT,permeability_stdev
FLOAT,permeability_p10
FLOAT,permeability_p50
FLOAT,permeability_p90
```

Other useful T>Map fields may follow these columns. Use `-77777` where no simulation result exists; this is the no-value marker used directly by the GRDECL append workflow.
