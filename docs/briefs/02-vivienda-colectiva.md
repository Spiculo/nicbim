<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Brief 02 — Edificio de vivienda colectiva, Cordón (Montevideo)

Benchmark role: **productivity**. The best demonstration of repetition and automation.

## Site

- Corner-free mid-block lot in Cordón: **17.3 m frontage × 40 m depth**, street to the south-east.
- Latitude −34.9030, longitude −56.1770, about 30 m above sea level. CRS EPSG:5382. Building +Y turned 30°
  from true north (`north` 30).
- Front line on the street (no setback), back setback 12 m (communal garden).

## Programme (ground + 9 floors + roof, 30–36 apartments)

| Level | Content |
|---|---|
| Planta baja | Entrance lobby, concierge, one shop (80 m²) on the street, bicycle room, waste room, access ramp to the basement |
| Subsuelo (−3.00) | 20 parking spaces, storage units, plant room |
| Niveles 1–8 (typical, every 2.90 m) | 4 apartments per floor: two 2-bedroom (65 m²) to the street, one 1-bedroom (45 m²) and one 3-bedroom (85 m²) to the garden |
| Nivel 9 | Two penthouses with terraces (setback 3 m from the street) |
| Azotea | Communal terrace, barbecue (parrillero), laundry, lift machine room, water tanks |

## Construction

- Reinforced concrete frame on a structural grid (about 5.5 × 6.0 m), 30 × 60 cm columns, 22 cm slabs.
- Central core: one stair (fire stair, 1.20 m) and two lifts.
- Façade: brick and glass bands with balconies on the street.

## The killer feature

Model the **typical floor once** as a model placed on levels 1–8 (models drawn once and placed on levels).
Then change the 2-bedroom apartment (for example the kitchen becomes open plan) and show every floor, schedule and
sheet update.

## Deliverables

1. Geolocated IFC with the grid, core, typical floors and penthouses.
2. Typical plan at 1:100 and apartment plans at 1:50, section through the core, street elevation.
3. Apartment schedule (type, area, floor), quantity takeoff by floor and for the building (walls, slabs, windows).
4. Sheets and the delivery package; IFC export.
