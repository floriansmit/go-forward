# Third-party software

## DFM Generator

GO-Forward can launch **DFM Generator** as a separate executable for dynamic fracture modelling. DFM Generator is developed independently by Michael J. Welch and contributors and is licensed under the Apache License 2.0.

The current GO-Forward demonstrator temporarily includes the approved binary at:

```text
external-tools/DFMGenerator/DFMGenerator_GRDECL.exe
```

This inclusion makes the demonstrator usable while the official upstream distribution is being prepared. It does not make DFM Generator part of the GO-Forward dashboard code. The dashboard starts it as a separate process, and users can select another local executable in **FFM Run DFM**.

Future official versions should be obtained from [JointFlow/DFMGenerator](https://github.com/JointFlow/DFMGenerator).

## Licence boundary

- GO-Forward source code and documentation: [MIT License](../../LICENSE).
- Bundled DFM Generator binary: Apache License 2.0, reproduced in `external-tools/DFMGenerator/LICENSE-Apache-2.0.txt`.

For the bundled binary's SHA-256 hash, attribution, and redistribution note, see [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
