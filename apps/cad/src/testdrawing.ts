// Ritningen and Lås mått as CAD's API answers them (#89 del b), for the web app's tests. Made from
// CAD's own answer (cad/views.py): a module 1213 × 680 with a rail short of gable A and a switch
// at the lower limit, and the photo test's MMM trapezoid with its line locked at 140 mm.
import type { DrawingView, LockProposal } from "./api";

export const DRAWING: DrawingView = {
  "module": "0e6c2f0a-1b2c-4d3e-8f40-5a6b7c8d9e0f",
  "base": 3,
  "latest": 3,
  "scale": "H0",
  "shape": {
    "kind": "straight",
    "length": 1213.0,
    "width": 680.0
  },
  "gables": [
    {
      "end": "A",
      "norm": null,
      "profile": null,
      "tracks": [
        53.0,
        580.0
      ]
    },
    {
      "end": "B",
      "norm": null,
      "profile": null,
      "tracks": [
        53.0,
        526.0,
        578.0
      ]
    }
  ],
  "graph": {
    "geometry": "mm",
    "nodes": [
      {
        "id": "n1",
        "type": "module_joint",
        "at": [
          0.0,
          53.0
        ],
        "gable": "A",
        "track": 1
      },
      {
        "id": "n2",
        "type": "module_joint",
        "at": [
          0.0,
          580.0
        ],
        "gable": "A",
        "track": 2
      },
      {
        "id": "n3",
        "type": "module_joint",
        "at": [
          1213.0,
          53.0
        ],
        "gable": "B",
        "track": 1
      },
      {
        "id": "n4",
        "type": "module_joint",
        "at": [
          1213.0,
          526.0
        ],
        "gable": "B",
        "track": 2
      },
      {
        "id": "n5",
        "type": "module_joint",
        "at": [
          1213.0,
          578.0
        ],
        "gable": "B",
        "track": 3
      },
      {
        "id": "n6",
        "type": "joint",
        "at": [
          51.0,
          53.0
        ],
        "gable": null,
        "track": null
      },
      {
        "id": "n9",
        "type": "switch",
        "at": [
          230.0,
          579.621
        ],
        "gable": null,
        "track": null
      }
    ],
    "pieces": [
      {
        "id": "s7",
        "start": "n6",
        "end": "n3",
        "segments": [
          {
            "kind": "line",
            "start": [
              51.0,
              53.0
            ],
            "end": [
              1213.0,
              53.0
            ]
          }
        ],
        "track": null,
        "origin": {
          "source": "drawn",
          "certainty": "confirmed"
        }
      },
      {
        "id": "s8",
        "start": "n2",
        "end": "n9",
        "segments": [
          {
            "kind": "line",
            "start": [
              0.0,
              580.0
            ],
            "end": [
              230.0,
              579.621
            ]
          }
        ],
        "track": null,
        "origin": {
          "source": "drawn",
          "certainty": "confirmed"
        }
      },
      {
        "id": "s10",
        "start": "n9",
        "end": "n5",
        "segments": [
          {
            "kind": "line",
            "start": [
              230.0,
              579.621
            ],
            "end": [
              1213.0,
              578.0
            ]
          }
        ],
        "track": null,
        "origin": {
          "source": "drawn",
          "certainty": "confirmed"
        }
      },
      {
        "id": "s11",
        "start": "n9",
        "end": "n4",
        "segments": [
          {
            "kind": "arc",
            "start": [
              230.0,
              579.621
            ],
            "end": [
              245.975,
              579.169
            ],
            "center": [
              229.505,
              279.621
            ],
            "radius": 300.0,
            "clockwise": false
          },
          {
            "kind": "line",
            "start": [
              245.975,
              579.169
            ],
            "end": [
              1213.0,
              526.0
            ]
          }
        ],
        "track": null,
        "origin": {
          "source": "drawn",
          "certainty": "confirmed"
        }
      }
    ],
    "switches": [
      {
        "id": "v12",
        "node": "n9",
        "type": "ordinary",
        "trunk": "s8",
        "straight": "s10",
        "diverging": "s11",
        "radius": 300.0,
        "angle": 3.05,
        "origin": {
          "source": "drawn",
          "certainty": "confirmed"
        },
        "number": "1",
        "design": null,
        "toward": "B",
        "locked": false
      }
    ],
    "labels": [],
    "complete": false,
    "issued": 12
  },
  "drawing": {
    "source": "drawn",
    "smoothing": "normal",
    "answers": [],
    "lines": [],
    "locks": [],
    "ids": [
      {
        "old": [
          "s8"
        ],
        "new": [
          "s8",
          "s10"
        ],
        "why": "switch"
      }
    ],
    "plan_approved": false
  },
  "checks": [
    {
      "key": "open_end:n1",
      "kind": "open_end",
      "source": "code",
      "at": [
        0.0,
        53.0
      ],
      "title": "Gavel A · spår 1 går inte in i modulen",
      "text": "Gavelspåret har inget spår i ritningen. Rita det, eller svara att det slutar vid gaveln.",
      "refs": [
        "n1"
      ],
      "choices": [
        {
          "id": "slutar",
          "text": "Spåret slutar vid gaveln",
          "closes": true,
          "action": null
        }
      ],
      "answer": null,
      "assumed": false
    },
    {
      "key": "short_rail:n6:A:51",
      "kind": "short_rail",
      "source": "code",
      "at": [
        51.0,
        53.0
      ],
      "title": "Rälsen slutar 51 mm före gavel A",
      "text": "Spårbiten når inte fram till gaveln och har ingen skarv där. Är det plats för en passbit?",
      "refs": [
        "n6",
        "s7"
      ],
      "choices": [
        {
          "id": "passbit",
          "text": "Det är en passbit",
          "closes": true,
          "action": null
        },
        {
          "id": "hela-vagen",
          "text": "Rälsen går ända fram",
          "closes": true,
          "action": null
        }
      ],
      "answer": null,
      "assumed": false
    },
    {
      "key": "switch_radius:v12:300",
      "kind": "switch_radius",
      "source": "code",
      "at": [
        230.0,
        579.6
      ],
      "title": "Växel 1: radien blev 300 mm",
      "text": "Det är vid nedre gränsen, 300 mm i H0. Välj växeltyp så används rätt radie.",
      "refs": [
        "v12",
        "n9"
      ],
      "choices": [
        {
          "id": "valj-typ",
          "text": "Välj växeltyp",
          "closes": false,
          "action": "design"
        },
        {
          "id": "radien-stammer",
          "text": "Radien stämmer",
          "closes": true,
          "action": null
        }
      ],
      "answer": null,
      "assumed": true
    }
  ],
  "switches": [
    {
      "id": "v12",
      "number": "1",
      "leaves": "spår från A2 mot B2",
      "from_a": 230.0,
      "radius": 300.0,
      "angle": 3.05,
      "side": "left",
      "toward": "B",
      "design": "okand",
      "matched": null,
      "assumed": true,
      "locked": false,
      "at": [
        230.0,
        579.6
      ],
      "origin": {
        "source": "drawn",
        "certainty": "confirmed"
      }
    }
  ],
  "designs": [
    {
      "id": "okand",
      "name": "Okänd",
      "scale": null,
      "radius": null,
      "angle": null,
      "source": null
    },
    {
      "id": "h0-r830-114",
      "name": "R 830 · 11,4°",
      "scale": "H0",
      "radius": 830.0,
      "angle": 11.4,
      "source": "Växeltyperna i en station läst ur AnyRail (specen, importen från AnyRail)."
    },
    {
      "id": "h0-r970-95",
      "name": "R 970 · 9,5°",
      "scale": "H0",
      "radius": 970.0,
      "angle": 9.5,
      "source": "Växeltyperna i en station läst ur AnyRail (specen, importen från AnyRail)."
    },
    {
      "id": "h0-r1880-72",
      "name": "R 1880 · 7,2°",
      "scale": "H0",
      "radius": 1880.0,
      "angle": 7.2,
      "source": "Växeltyperna i en station läst ur AnyRail (specen, importen från AnyRail)."
    },
    {
      "id": "h0-r2100-63",
      "name": "R 2100 · 6,3°",
      "scale": "H0",
      "radius": 2100.0,
      "angle": 6.3,
      "source": "Växeltyperna i en station läst ur AnyRail (specen, importen från AnyRail)."
    },
    {
      "id": "h0-r2200-94",
      "name": "R 2200 · 9,4°",
      "scale": "H0",
      "radius": 2200.0,
      "angle": 9.4,
      "source": "Växeltyperna i en station läst ur AnyRail (specen, importen från AnyRail)."
    }
  ],
  "smoothing_levels": [
    {
      "level": "off",
      "name": "Av",
      "min_radius": null,
      "max_deviation": null,
      "text": "Av: linjen blir kvar som den ritades, raka bitar mellan punkterna."
    },
    {
      "level": "light",
      "name": "Lätt",
      "min_radius": 300.0,
      "max_deviation": 4.1,
      "text": "Följer linjen nära och behåller växlarnas snäva ben. Lätt: minsta radie 300 mm och högst 4,1 mm från linjen."
    },
    {
      "level": "normal",
      "name": "Normal",
      "min_radius": 400.0,
      "max_deviation": 9.0,
      "text": "Knaggliga linjer blir mjuka kurvor. Normal: minsta radie 400 mm och högst 9 mm från linjen."
    },
    {
      "level": "strong",
      "name": "Kraftig",
      "min_radius": 600.0,
      "max_deviation": 16.5,
      "text": "För en linje som vandrar mellan rälerna. Kraftig: minsta radie 600 mm och högst 16,5 mm från linjen."
    }
  ],
  "limits": {
    "scale": "H0",
    "gauge": 16.5,
    "min_radius": 400.0,
    "switch_min_radius": 300.0,
    "kink": 1.43,
    "gable_tolerance": 2.0,
    "design_tolerance": 0.1
  },
  "stats": {
    "track_length": 3359.5,
    "switches": 1,
    "deviation": null
  },
  "changed": true
};

export const PROPOSAL: LockProposal = {
  "solved": true,
  "why": "MMM-normen säger 140 mm från Kant 1. Linjen låg 2 mm ifrån, så måttet låses och kurvan räknas om.",
  "radii": "same",
  "gables": [
    {
      "gable": "A",
      "track": 1,
      "value": 140.0,
      "line": 138.0,
      "norm": "mmm",
      "profile": "MMM enkelspår"
    },
    {
      "gable": "B",
      "track": 1,
      "value": 140.0,
      "line": 141.0,
      "norm": "mmm",
      "profile": "MMM enkelspår"
    }
  ],
  "parts": [
    {
      "kind": "straight",
      "label": "Rakt från gavel A",
      "length": 82.2,
      "radius": null,
      "angle": 0.0
    },
    {
      "kind": "arc",
      "label": "Båge",
      "length": 187.2,
      "radius": 567.5,
      "angle": 18.9
    },
    {
      "kind": "straight",
      "label": "Rakt",
      "length": 217.0,
      "radius": null,
      "angle": 18.9
    },
    {
      "kind": "arc",
      "label": "Båge",
      "length": 187.2,
      "radius": 567.5,
      "angle": 18.9
    },
    {
      "kind": "straight",
      "label": "Rakt till gavel B",
      "length": 29.9,
      "radius": null,
      "angle": 0.0
    }
  ],
  "old": [
    [
      0.0,
      138.0
    ],
    [
      9.9,
      138.0
    ],
    [
      19.8,
      137.9
    ],
    [
      29.7,
      138.1
    ],
    [
      39.7,
      138.1
    ],
    [
      49.6,
      137.6
    ],
    [
      59.5,
      137.5
    ],
    [
      69.4,
      138.4
    ],
    [
      79.3,
      137.9
    ],
    [
      89.2,
      138.2
    ],
    [
      99.0,
      139.4
    ],
    [
      108.9,
      139.5
    ],
    [
      118.8,
      140.7
    ],
    [
      128.7,
      141.2
    ],
    [
      138.5,
      142.5
    ],
    [
      148.4,
      143.2
    ],
    [
      158.2,
      145.0
    ],
    [
      167.9,
      146.8
    ],
    [
      177.8,
      148.1
    ],
    [
      187.5,
      150.2
    ],
    [
      197.2,
      152.1
    ],
    [
      207.0,
      153.6
    ],
    [
      216.5,
      156.5
    ],
    [
      226.1,
      158.8
    ],
    [
      235.8,
      161.1
    ],
    [
      245.4,
      163.6
    ],
    [
      254.6,
      167.2
    ],
    [
      264.2,
      169.8
    ],
    [
      273.5,
      173.2
    ],
    [
      282.8,
      176.6
    ],
    [
      292.3,
      179.6
    ],
    [
      301.6,
      183.1
    ],
    [
      311.1,
      185.8
    ],
    [
      320.4,
      189.4
    ],
    [
      329.8,
      192.3
    ],
    [
      339.1,
      196.0
    ],
    [
      348.4,
      199.2
    ],
    [
      358.0,
      201.7
    ],
    [
      367.4,
      204.9
    ],
    [
      376.8,
      208.2
    ],
    [
      385.9,
      212.1
    ],
    [
      395.4,
      214.9
    ],
    [
      404.7,
      218.3
    ],
    [
      414.2,
      221.2
    ],
    [
      423.5,
      224.6
    ],
    [
      432.9,
      227.8
    ],
    [
      442.3,
      231.0
    ],
    [
      451.6,
      234.4
    ],
    [
      461.0,
      237.6
    ],
    [
      470.3,
      241.0
    ],
    [
      479.8,
      243.9
    ],
    [
      489.2,
      246.9
    ],
    [
      498.8,
      249.6
    ],
    [
      508.3,
      252.3
    ],
    [
      518.0,
      254.4
    ],
    [
      527.8,
      256.2
    ],
    [
      537.3,
      259.0
    ],
    [
      547.0,
      261.0
    ],
    [
      556.8,
      262.8
    ],
    [
      566.6,
      264.1
    ],
    [
      576.4,
      265.8
    ],
    [
      586.2,
      266.7
    ],
    [
      596.0,
      268.5
    ],
    [
      605.9,
      269.3
    ],
    [
      615.8,
      270.0
    ],
    [
      625.7,
      270.5
    ],
    [
      635.5,
      271.9
    ],
    [
      645.4,
      272.5
    ],
    [
      655.3,
      271.9
    ],
    [
      665.2,
      272.8
    ],
    [
      675.1,
      272.4
    ],
    [
      685.0,
      272.5
    ]
  ],
  "new": [
    {
      "kind": "line",
      "start": [
        0.0,
        140.0
      ],
      "end": [
        82.167,
        140.0
      ]
    },
    {
      "kind": "arc",
      "start": [
        82.167,
        140.0
      ],
      "end": [
        265.989,
        170.598
      ],
      "center": [
        82.167,
        707.466
      ],
      "radius": 567.466,
      "clockwise": true
    },
    {
      "kind": "line",
      "start": [
        265.989,
        170.598
      ],
      "end": [
        471.316,
        240.902
      ]
    },
    {
      "kind": "arc",
      "start": [
        471.316,
        240.902
      ],
      "end": [
        655.139,
        271.5
      ],
      "center": [
        655.139,
        -295.966
      ],
      "radius": 567.466,
      "clockwise": false
    },
    {
      "kind": "line",
      "start": [
        655.139,
        271.5
      ],
      "end": [
        685.0,
        271.5
      ]
    }
  ],
  "tangents": [
    [
      82.2,
      140.0
    ],
    [
      266.0,
      170.6
    ],
    [
      471.3,
      240.9
    ],
    [
      655.1,
      271.5
    ]
  ],
  "deviation": {
    "median": 0.29,
    "max": 2.48,
    "count": 72
  },
  "lock": {
    "op": "lock",
    "piece": null,
    "a": null,
    "b": null,
    "radii": "same"
  }
};
