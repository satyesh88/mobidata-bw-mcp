# Heilbronn Hbf accessibility and station-complex audit

Checked read-only through the server venv on 18 October 2026. These are the relevant
raw fields. [Extracted rows](../tests/fixtures/bfrk/heilbronn_hbf.json) include parent IDs and coordinates.

## BFRK platform edges

All seven STEIG_Name values are Hauptbahnhof. No track number is explicit in these
CSV rows. No edge-to-track or edge-to-lift mapping can be asserted from these fields.
GTFS separately supplies explicit track labels for matching DHIDs; those are not used
here to silently rename BFRK edges.

| ID | STEIG_Name | Erfassungsdatum |
| --- | --- | --- |
| de:08121:26:4:5 | Hauptbahnhof | 02.06.2021 |
| de:08121:26:5:6 | Hauptbahnhof | 01.06.2021 |
| de:08121:26:5:7 | Hauptbahnhof | 01.06.2021 |
| de:08121:26:1:1 | Hauptbahnhof | 02.06.2021 |
| de:08121:26:3:2 | Hauptbahnhof | 02.06.2021 |
| de:08121:26:3:3 | Hauptbahnhof | 01.06.2021 |
| de:08121:26:4:4 | Hauptbahnhof | 02.06.2021 |

[Raw BFRK_Haltesteig.csv](https://www.nvbw.de/fileadmin/user_upload/service/open_data/haltestellen/SPNV/BFRK_Haltesteig.csv)

## Raw lift, ramp and stair connections

These descriptions are not a verified mapping to the unnamed edges. In particular,
AUFZUG-2 says Gl 3/4 while nearby stairs say Gl 2/3. BSTG refers to a platform label
and is not automatically equivalent to a track number.

### Aufzug

| ID | Verbindungsfunktion | Erfassungsdatum |
| --- | --- | --- |
| INFRA-de:08121:26-AUFZUG-6 | BuGa= Brücke, Süd-Nord-Verbindung über Gleise | 28.10.2024 |
| INFRA-de:08121:26-AUFZUG-1 | Bahnhofsgebäude zu Unterführung | 01.06.2021 |
| INFRA-de:08121:26-AUFZUG-5 | Nordseite auf BuGa-Brücke, zum BhfGeb | 28.10.2024 |
| INFRA-de:08121:26-AUFZUG-2 | Unterführung zu Gl 3/4 | 01.06.2021 |
| INFRA-de:08121:26-AUFZUG-3 | Unterführung zu Gl 6/7 | 01.06.2021 |
| INFRA-de:08121:26-AUFZUG-4 | Unterführung zu BSTG 4/5 | 01.06.2021 |

[Raw BFRK_Aufzug.csv](https://www.nvbw.de/fileadmin/user_upload/service/open_data/haltestellen/SPNV/BFRK_Aufzug.csv)

### Rampe

| ID | Verbindungsfunktion | Erfassungsdatum |
| --- | --- | --- |
| INFRA-de:08121:26-RAMPE-1 | Neigung eigentlich 29,6! | 02.06.2021 |
| INFRA-de:08121:26-RAMPE-2 | Bahnhofsgebäude bei Tür 1 zu BSTG 1 | 01.06.2021 |
| INFRA-de:08121:26-RAMPE-3 | Bahnhofsgebäude bei Tür 2 zu Gl1 | 01.06.2021 |
| INFRA-de:08121:26-RAMPE-4 | Taxistand bei B+R zu Gl 1 | 01.06.2021 |
| INFRA-de:08121:26-RAMPE-5 | Bahnsteig 1 Ri Bahnhofsmission/Behindertentoilette | 01.06.2021 |
| INFRA-de:08121:26-RAMPE-6 | Bahnsteig 1 zu BehindertenWC/Info | 01.06.2021 |
| INFRA-de:08121:26-RAMPE-7 | verschlossene Tür zu BSTG 1 (hier wohl Mitarbeiterraum DB Regio) | 01.06.2021 |

[Raw BFRK_Rampe.csv](https://www.nvbw.de/fileadmin/user_upload/service/open_data/haltestellen/SPNV/BFRK_Rampe.csv)

### Treppe

| ID | Verbindungsfunktion | Erfassungsdatum |
| --- | --- | --- |
| INFRA-de:08121:26-TREPPE-1 | vor Tür von Abellio | 02.06.2021 |
| INFRA-de:08121:26-TREPPE-2 | Zwischenebene bei WC zu Gl 1 | 01.06.2021 |
| INFRA-de:08121:26-TREPPE-3 | Bahnsteig 1 zur Bahnhofsmission | 01.06.2021 |
| INFRA-de:08121:26-TREPPE-15 | Süd-Noed-Verbindung östlich vom BhfGeb | 28.10.2024 |
| INFRA-de:08121:26-TREPPE-4 | Bahnsteig zu Tür von Informationsstelle | 02.06.2021 |
| INFRA-de:08121:26-TREPPE-14 | Nord-Süd-Verbindung östlich vom BhfGeb | 28.10.2024 |
| INFRA-de:08121:26-TREPPE-5 | Unterführung zu Gl 2/3 | 01.06.2021 |
| INFRA-de:08121:26-TREPPE-6 | Unterführung zu Gl 2/3 bei Aufzug | 01.06.2021 |
| INFRA-de:08121:26-TREPPE-7 | Unterführung zu BSTG 4/5 | 01.06.2021 |
| INFRA-de:08121:26-TREPPE-8 | Unterführung zu Gl 4/5 bei Aufzug | 01.06.2021 |
| INFRA-de:08121:26-TREPPE-9 | Unterführung zu GL 6/7 | 01.06.2021 |
| INFRA-de:08121:26-TREPPE-10 | Unterführung zu GL 6/7 | 01.06.2021 |
| INFRA-de:08121:26-TREPPE-11 | von Unterführung zu Zwischenebene, von da weiter zu Bahnhofsgebäude/WC/Gl1 | 01.06.2021 |
| INFRA-de:08121:26-TREPPE-12 | Zwischenebene weiter zu Bahnhofsgebäude | 01.06.2021 |
| INFRA-de:08121:26-TREPPE-13 | vor Eingang Ost | 02.06.2021 |

[Raw BFRK_Treppe.csv](https://www.nvbw.de/fileadmin/user_upload/service/open_data/haltestellen/SPNV/BFRK_Treppe.csv)

## GTFS station complex

The old lookup selected the mainline group (9 IDs). The adjacent forecourt Stadtbahn
group has a separate parent. Its explicit Hbf/Willy-Brandt-Pl. names and coordinates
immediately outside the main station identify the same station complex. The revised
lookup includes both groups (17 IDs). Explicit individual platform IDs remain scoped
only to that platform.

| stop_id | stop_name | parent_station |
| --- | --- | --- |
| de:08121:26_Parent | Heilbronn Hauptbahnhof | — |
| de:08121:26 | Heilbronn Hauptbahnhof | de:08121:26_Parent |
| de:08121:26:1:1 | Heilbronn Hauptbahnhof Gleis 1 | de:08121:26_Parent |
| de:08121:26:3:2 | Heilbronn Hauptbahnhof Gleis 2 | de:08121:26_Parent |
| de:08121:26:3:3 | Heilbronn Hauptbahnhof Gleis 3 | de:08121:26_Parent |
| de:08121:26:4:4 | Heilbronn Hauptbahnhof Gleis 4 | de:08121:26_Parent |
| de:08121:26:4:5 | Heilbronn Hauptbahnhof Gleis 5 | de:08121:26_Parent |
| de:08121:26:5:6 | Heilbronn Hauptbahnhof Gleis 6 | de:08121:26_Parent |
| de:08121:26:5:7 | Heilbronn Hauptbahnhof Gleis 7 | de:08121:26_Parent |
| de:08121:1114_Parent | Heilbronn Hbf/Willy-Brandt-Pl. | — |
| de:08121:1114 | Heilbronn Hbf/Willy-Brandt-Pl. | de:08121:1114_Parent |
| de:08121:1114:2:0 | Heilbronn Hbf/Willy-Brandt-Pl. | de:08121:1114_Parent |
| de:08121:1115:0:1 | Heilbronn Hbf/Willy-Brandt-Pl. (Steig A) | — |
| de:08121:1116:0:0 | Heilbronn Hbf/Willy-Brandt-Pl. (Steig B) | — |
| de:08121:1114:3:1 | Heilbronn Hbf/Willy-Brandt-Pl. Gleis 1 | de:08121:1114_Parent |
| de:08121:1114:3:2 | Heilbronn Hbf/Willy-Brandt-Pl. Gleis 2 | de:08121:1114_Parent |
| de:08121:1114:3:3 | Heilbronn Hbf/Willy-Brandt-Pl. Gleis 3 | de:08121:1114_Parent |

[GTFS stops API](https://api.mobidata-bw.de/gtfs/stops)

All returned wheelchair_boarding fields were null: no accessibility info in the
timetable, not evidence of inaccessibility. Numeric GTFS flags normalize as
0 → unknown, 1 → accessible, 2 → not_accessible, for both trip and stop flags.

The expanded 17-stop candidate was verified in memory in the server venv, without
writing server files or restarting services: lookup 153.5 ms, PostgREST 900.0 ms,
formatting 0.2 ms, total 1054.2 ms (10 departures); cached total 0.4 ms.
Including the forecourt stops does not by itself establish a step-free interchange.
