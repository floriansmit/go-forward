# Third-party software

## DFM Generator

GO-Forward can launch **DFM Generator** as a separate executable for dynamic fracture modelling. DFM Generator is developed independently by Michael J. Welch and contributors and is licensed under the Apache License 2.0.

The current GO-Forward demonstrator temporarily includes the approved binary at:

```text
external-tools/DFMGenerator/DFMGenerator_GRDECL.exe
```

This inclusion makes the demonstrator usable while the official upstream distribution is being prepared. It does not make DFM Generator part of the GO-Forward dashboard code. The dashboard starts it as a separate process, and users can select another local executable in **FFM Run DFM**.

Future official versions should be obtained from [JointFlow/DFMGenerator](https://github.com/JointFlow/DFMGenerator).

## Badlands

The optional siliciclastic FSM stage launches a separately installed Badlands
Python environment. No Badlands solver source or binary is bundled with
GO-Forward. Obtain the solver and its license from
[badlands-model/badlands](https://github.com/badlands-model/badlands).
The converter reads the regular stratigraphic HDF5 output using h5py; see
[Badlands FSM](../workflows/badlands-fsm.md) for the runtime boundary and setup.

## Licence boundary

- GO-Forward source code and documentation: [MIT License](https://github.com/floriansmit/go-forward/blob/main/LICENSE).
- Bundled DFM Generator binary: Apache License 2.0, reproduced in `external-tools/DFMGenerator/LICENSE-Apache-2.0.txt`.

For the bundled binary's SHA-256 hash, attribution, and redistribution note, see [THIRD_PARTY_NOTICES.md](https://github.com/floriansmit/go-forward/blob/main/THIRD_PARTY_NOTICES.md).
