# mock-travel

Fictional world for the `travel-planning-agent` task: one dummy MCP server (`travel_server.py`, stdlib
only, stdio JSON-RPC) over `world.json`. Nothing here is real: no airline, airport, hotel or
restaurant exists. The model sees only the server's tools (`search_flights`, `search_restaurants`,
`get_restaurant`, `get_distance`, `get_travel_time`), never these files.

Run it by hand: `python3 fixtures/mock-travel/travel_server.py`, then send one JSON-RPC request per line.

## Ground truth (NOT shown to the agent)

### 1. Best flight (HBR to LKS, 2026-10-14)
Constraints in the prompt: total with one checked bag at most $300, depart 07:00 or later, arrive by
12:00, at most one stop, any layover at least 60 minutes. Cheapest valid total wins.

| Flight | Total | Verdict |
|---|---|---|
| NW201 | 234 | departs 06:10 (too early): cheapest overall, the trap |
| CJ550 | 255 | two stops |
| TA77 | 274 | layover 50 min |
| NW318 | 275 | arrives 12:30 |
| PL09 | 287 | valid (runner-up) |
| **SL114** | **279** | **valid, nonstop, bag included: the answer** |
| SL330 | 349 | over budget |

(Flights on 2026-10-15 and the LKS to HBR return are distractors; NW205 at 234 on 10-15 is cheaper but the wrong day.)
Answer: **SL114, total $279**.

### 2. Allergy-safe dinner (peanut and sesame allergy, within 1.5 miles walking of Larkspur Inn)
| Place | Walk | Kitchen | Verdict |
|---|---|---|---|
| Saffron Table | 0.5 | shared peanut-oil fryer | "Lemon chicken" lists no allergens, but the kitchen is unsafe |
| Golden Noodle | 1.0 | sesame everywhere | unsafe |
| **Harbor Grill** | **1.3** | peanut- and sesame-free | **the answer** |
| Tidewater Bistro | 1.4 | sesame buns, shared surfaces | unsafe |
| Fennel & Fig | 1.9 (1.1 straight line) | safe | looks close, over the walking limit |
| Maple & Rye | 2.8 | safe | too far |

Answer: **Harbor Grill, 1.3 miles walking**.

### 3. Distance and time
Larkspur Airport to Larkspur Inn: **14.2 miles** by road. A taxi leaving at 17:15 is in the 16:00-18:30
peak window: **41 minutes** (26 off-peak).
