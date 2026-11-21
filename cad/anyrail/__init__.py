"""Import from AnyRail (#91, TKL16, ANYRAIL-01–22): AnyRail's files become modules with gables and
tracks, an assembly, exports, and the track graph for Studio.

The method is the specification's (trainmeet-cad-anyrail-import.md), rule by rule:

- reader.py reads AnyRail 2.0's XML export and AnyRail's own file (.any, a Boost binary archive)
  into the same Layout: parts, endpoints and connections, in mm with y down. Both readers are
  hardened: size limits, part and endpoint limits, no DOCTYPE or entities, and a bounds-checked
  binary reader; a file that cannot be read gets a Swedish reason.
- interpret.py is the interpretation (2. Tolkningsregler, 3. Geometrifilter, 4. Kontroller) with
  the measures the owner may change per file (AR5, AR6): pure functions, deterministic, the same
  file and the same measures always give the same result.
- outputs.py writes the exports: DXF for the station and per module (cad/dxf.py), the gable
  profiles and the switch list as CSV.
- service.py and api.py keep the uploaded file in CAD only (it never leaves CAD, ANYRAIL-08) with
  its measures, and make the modules and the assembly (Skapa modulerna).

No code here names a station: the rules are generic, and the reference stations are tests.
"""
