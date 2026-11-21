// Import från AnyRail as CAD's API answers it (#91), for the web app's tests. Made by CAD's own code
// (cad/anyrail/service.py) from the synthetic station in cad/tests/anyrail_syntetisk.py: six modules,
// four switches of which one is assumed, a crossing, a loop, a backward piece and a loose track.
import type { AnyRailImport } from "./api";

export const ANYRAIL: AnyRailImport = {
 "id": "5b0c2a1e-7d3f-4e60-9a81-2b3c4d5e6f70",
 "name": "Exempelstation.xml",
 "format": "xml",
 "library": null,
 "revision": 1,
 "scale": "H0",
 "measures": {
  "track_width": 16.5,
  "join_distance": 40.0,
  "lateral": 6.0,
  "crossing_node": 30.0,
  "crossing_angle": 5.0,
  "backward_length": 200.0,
  "tight_radius": 400.0
 },
 "defaults": {
  "track_width": 16.5,
  "join_distance": 40.0,
  "lateral": 6.0,
  "crossing_node": 30.0,
  "crossing_angle": 5.0,
  "backward_length": 200.0,
  "tight_radius": 400.0
 },
 "area": [
  6400.0,
  1500.0
 ],
 "modules": [
  {
   "key": "m1",
   "number": "1",
   "name": "Modul 1",
   "end": false,
   "at": [
    900.0,
    0.0
   ],
   "angle": -0.0,
   "outline": [
    [
     900.0,
     0.0
    ],
    [
     2400.0,
     0.0
    ],
    [
     2400.0,
     700.0
    ],
    [
     900.0,
     700.0
    ]
   ],
   "shape": {
    "kind": "straight",
    "length": 1500.0,
    "width": 700.0
   },
   "standard": "1500 × 700",
   "gables": [
    {
     "end": "A",
     "norm": null,
     "profile": null,
     "tracks": [
      140.0,
      197.0
     ]
    },
    {
     "end": "B",
     "norm": null,
     "profile": null,
     "tracks": [
      134.9,
      140.0,
      197.0,
      450.0
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
       140.0
      ],
      "gable": "A",
      "track": 1
     },
     {
      "id": "n2",
      "type": "module_joint",
      "at": [
       0.0,
       197.0
      ],
      "gable": "A",
      "track": 2
     },
     {
      "id": "n3",
      "type": "switch",
      "at": [
       200.0,
       197.0
      ],
      "gable": null,
      "track": null
     },
     {
      "id": "n4",
      "type": "joint",
      "at": [
       559.317,
       197.0
      ],
      "gable": null,
      "track": null
     },
     {
      "id": "n5",
      "type": "joint",
      "at": [
       559.317,
       226.541
      ],
      "gable": null,
      "track": null
     },
     {
      "id": "n6",
      "type": "switch",
      "at": [
       1350.0,
       140.0
      ],
      "gable": null,
      "track": null
     },
     {
      "id": "n7",
      "type": "joint",
      "at": [
       1400.0,
       450.0
      ],
      "gable": null,
      "track": null
     },
     {
      "id": "n8",
      "type": "module_joint",
      "at": [
       1500.0,
       134.881
      ],
      "gable": "B",
      "track": 1
     },
     {
      "id": "n9",
      "type": "module_joint",
      "at": [
       1500.0,
       140.0
      ],
      "gable": "B",
      "track": 2
     },
     {
      "id": "n10",
      "type": "module_joint",
      "at": [
       1500.0,
       197.0
      ],
      "gable": "B",
      "track": 3
     },
     {
      "id": "n11",
      "type": "module_joint",
      "at": [
       1500.0,
       450.0
      ],
      "gable": "B",
      "track": 4
     }
    ],
    "pieces": [
     {
      "id": "s12",
      "start": "n1",
      "end": "n6",
      "segments": [
       {
        "kind": "line",
        "start": [
         0.0,
         140.0
        ],
        "end": [
         1350.0,
         140.0
        ]
       }
      ],
      "track": null,
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "150"
      }
     },
     {
      "id": "s13",
      "start": "n2",
      "end": "n3",
      "segments": [
       {
        "kind": "line",
        "start": [
         0.0,
         197.0
        ],
        "end": [
         200.0,
         197.0
        ]
       }
      ],
      "track": null,
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "158"
      }
     },
     {
      "id": "s14",
      "start": "n3",
      "end": "n4",
      "segments": [
       {
        "kind": "line",
        "start": [
         200.0,
         197.0
        ],
        "end": [
         559.317,
         197.0
        ]
       }
      ],
      "track": "3",
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "159"
      }
     },
     {
      "id": "s15",
      "start": "n3",
      "end": "n5",
      "segments": [
       {
        "kind": "arc",
        "start": [
         200.0,
         197.0
        ],
        "end": [
         559.317,
         226.541
        ],
        "center": [
         200.003,
         2396.982
        ],
        "radius": 2199.982,
        "clockwise": true
       }
      ],
      "track": "4",
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "159"
      }
     },
     {
      "id": "s16",
      "start": "n4",
      "end": "n10",
      "segments": [
       {
        "kind": "line",
        "start": [
         559.317,
         197.0
        ],
        "end": [
         1500.0,
         197.0
        ]
       }
      ],
      "track": "3",
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "160"
      }
     },
     {
      "id": "s17",
      "start": "n5",
      "end": "n7",
      "segments": [
       {
        "kind": "arc",
        "start": [
         559.317,
         226.541
        ],
        "end": [
         611.559,
         236.663
        ],
        "center": [
         400.205,
         1187.644
        ],
        "radius": 974.185,
        "clockwise": true
       },
       {
        "kind": "arc",
        "start": [
         611.559,
         236.663
        ],
        "end": [
         663.267,
         249.273
        ],
        "center": [
         329.987,
         1503.584
        ],
        "radius": 1297.833,
        "clockwise": true
       },
       {
        "kind": "arc",
        "start": [
         663.267,
         249.273
        ],
        "end": [
         715.784,
         264.234
        ],
        "center": [
         269.771,
         1730.21
        ],
        "radius": 1532.323,
        "clockwise": true
       },
       {
        "kind": "arc",
        "start": [
         715.784,
         264.234
        ],
        "end": [
         767.837,
         280.75
        ],
        "center": [
         47.606,
         2460.435
        ],
        "radius": 2295.596,
        "clockwise": true
       },
       {
        "kind": "arc",
        "start": [
         767.837,
         280.75
        ],
        "end": [
         873.255,
         317.468
        ],
        "center": [
         -324.357,
         3586.132
        ],
        "radius": 3481.155,
        "clockwise": true
       },
       {
        "kind": "arc",
        "start": [
         873.255,
         317.468
        ],
        "end": [
         978.249,
         355.42
        ],
        "center": [
         5294.575,
         -11749.716
        ],
        "radius": 12851.653,
        "clockwise": false
       },
       {
        "kind": "arc",
        "start": [
         978.249,
         355.42
        ],
        "end": [
         1030.869,
         373.836
        ],
        "center": [
         2574.033,
         -4119.956
        ],
        "radius": 4751.37,
        "clockwise": false
       },
       {
        "kind": "arc",
        "start": [
         1030.869,
         373.836
        ],
        "end": [
         1083.792,
         391.354
        ],
        "center": [
         1845.413,
         -1998.167
        ],
        "radius": 2507.963,
        "clockwise": false
       },
       {
        "kind": "arc",
        "start": [
         1083.792,
         391.354
        ],
        "end": [
         1136.331,
         407.312
        ],
        "center": [
         1693.798,
         -1522.489
        ],
        "radius": 2008.707,
        "clockwise": false
       },
       {
        "kind": "arc",
        "start": [
         1136.331,
         407.312
        ],
        "end": [
         1189.365,
         421.516
        ],
        "center": [
         1526.149,
         -942.132
        ],
        "radius": 1404.62,
        "clockwise": false
       },
       {
        "kind": "arc",
        "start": [
         1189.365,
         421.516
        ],
        "end": [
         1241.83,
         433.242
        ],
        "center": [
         1479.229,
         -752.153
        ],
        "radius": 1208.933,
        "clockwise": false
       },
       {
        "kind": "arc",
        "start": [
         1241.83,
         433.242
        ],
        "end": [
         1294.816,
         442.274
        ],
        "center": [
         1424.989,
         -481.32
        ],
        "radius": 932.723,
        "clockwise": false
       },
       {
        "kind": "arc",
        "start": [
         1294.816,
         442.274
        ],
        "end": [
         1347.279,
         447.979
        ],
        "center": [
         1411.012,
         -382.15
        ],
        "radius": 832.572,
        "clockwise": false
       },
       {
        "kind": "arc",
        "start": [
         1347.279,
         447.979
        ],
        "end": [
         1400.0,
         450.0
        ],
        "center": [
         1400.0,
         -238.717
        ],
        "radius": 688.717,
        "clockwise": false
       }
      ],
      "track": "4",
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "167"
      }
     },
     {
      "id": "s18",
      "start": "n6",
      "end": "n9",
      "segments": [
       {
        "kind": "line",
        "start": [
         1350.0,
         140.0
        ],
        "end": [
         1500.0,
         140.0
        ]
       }
      ],
      "track": "2",
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "151"
      }
     },
     {
      "id": "s19",
      "start": "n6",
      "end": "n8",
      "segments": [
       {
        "kind": "arc",
        "start": [
         1350.0,
         140.0
        ],
        "end": [
         1500.0,
         134.881
        ],
        "center": [
         1350.003,
         -2059.982
        ],
        "radius": 2199.982,
        "clockwise": false
       }
      ],
      "track": "1",
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "151"
      }
     },
     {
      "id": "s20",
      "start": "n7",
      "end": "n11",
      "segments": [
       {
        "kind": "line",
        "start": [
         1400.0,
         450.0
        ],
        "end": [
         1500.0,
         450.0
        ]
       }
      ],
      "track": "4",
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "168"
      }
     }
    ],
    "switches": [
     {
      "id": "v21",
      "node": "n3",
      "type": "ordinary",
      "trunk": "s13",
      "straight": "s14",
      "diverging": "s15",
      "radius": 2200.0,
      "angle": 9.4,
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "159"
      },
      "number": "1",
      "design": null,
      "toward": "B",
      "locked": false
     },
     {
      "id": "v22",
      "node": "n6",
      "type": "ordinary",
      "trunk": "s12",
      "straight": "s18",
      "diverging": "s19",
      "radius": 2200.0,
      "angle": 9.4,
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "151"
      },
      "number": "2",
      "design": null,
      "toward": "B",
      "locked": false
     }
    ],
    "labels": [],
    "symbols": [],
    "complete": true,
    "issued": 22
   },
   "switches": 2,
   "assumed": 0,
   "checks": []
  },
  {
   "key": "m2",
   "number": "2a",
   "name": "Modul 2a",
   "end": false,
   "at": [
    2400.0,
    0.0
   ],
   "angle": -0.0,
   "outline": [
    [
     2400.0,
     0.0
    ],
    [
     3900.0,
     0.0
    ],
    [
     3900.0,
     350.0
    ],
    [
     2400.0,
     350.0
    ]
   ],
   "shape": {
    "kind": "straight",
    "length": 1500.0,
    "width": 350.0
   },
   "standard": "1500 × 350",
   "gables": [
    {
     "end": "A",
     "norm": null,
     "profile": null,
     "tracks": [
      134.9,
      140.0,
      197.0
     ]
    },
    {
     "end": "B",
     "norm": null,
     "profile": null,
     "tracks": [
      140.0,
      197.0
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
       134.881
      ],
      "gable": "A",
      "track": 1
     },
     {
      "id": "n2",
      "type": "module_joint",
      "at": [
       0.0,
       140.0
      ],
      "gable": "A",
      "track": 2
     },
     {
      "id": "n3",
      "type": "module_joint",
      "at": [
       0.0,
       197.0
      ],
      "gable": "A",
      "track": 3
     },
     {
      "id": "n4",
      "type": "joint",
      "at": [
       209.317,
       110.459
      ],
      "gable": null,
      "track": null
     },
     {
      "id": "n5",
      "type": "joint",
      "at": [
       209.317,
       140.0
      ],
      "gable": null,
      "track": null
     },
     {
      "id": "n6",
      "type": "joint",
      "at": [
       568.634,
       80.918
      ],
      "gable": null,
      "track": null
     },
     {
      "id": "n7",
      "type": "buffer_stop",
      "at": [
       900.0,
       80.918
      ],
      "gable": null,
      "track": null
     },
     {
      "id": "n8",
      "type": "module_joint",
      "at": [
       1500.0,
       140.0
      ],
      "gable": "B",
      "track": 1
     },
     {
      "id": "n9",
      "type": "module_joint",
      "at": [
       1500.0,
       197.0
      ],
      "gable": "B",
      "track": 2
     }
    ],
    "pieces": [
     {
      "id": "s10",
      "start": "n1",
      "end": "n4",
      "segments": [
       {
        "kind": "arc",
        "start": [
         0.0,
         134.881
        ],
        "end": [
         209.317,
         110.459
        ],
        "center": [
         -149.997,
         -2059.982
        ],
        "radius": 2199.982,
        "clockwise": false
       }
      ],
      "track": "1",
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "151"
      }
     },
     {
      "id": "s11",
      "start": "n2",
      "end": "n5",
      "segments": [
       {
        "kind": "line",
        "start": [
         0.0,
         140.0
        ],
        "end": [
         209.317,
         140.0
        ]
       }
      ],
      "track": "2",
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "151"
      }
     },
     {
      "id": "s12",
      "start": "n3",
      "end": "n9",
      "segments": [
       {
        "kind": "line",
        "start": [
         0.0,
         197.0
        ],
        "end": [
         1500.0,
         197.0
        ]
       }
      ],
      "track": "3",
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "161"
      }
     },
     {
      "id": "s13",
      "start": "n4",
      "end": "n6",
      "segments": [
       {
        "kind": "arc",
        "start": [
         209.317,
         110.459
        ],
        "end": [
         568.634,
         80.918
        ],
        "center": [
         568.631,
         2280.9
        ],
        "radius": 2199.982,
        "clockwise": true
       }
      ],
      "track": "1",
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "170"
      }
     },
     {
      "id": "s14",
      "start": "n5",
      "end": "n8",
      "segments": [
       {
        "kind": "line",
        "start": [
         209.317,
         140.0
        ],
        "end": [
         1500.0,
         140.0
        ]
       }
      ],
      "track": "2",
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "152"
      }
     },
     {
      "id": "s15",
      "start": "n6",
      "end": "n7",
      "segments": [
       {
        "kind": "line",
        "start": [
         568.634,
         80.918
        ],
        "end": [
         900.0,
         80.918
        ]
       }
      ],
      "track": "1",
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "171"
      }
     }
    ],
    "switches": [],
    "labels": [],
    "symbols": [],
    "complete": true,
    "issued": 15
   },
   "switches": 0,
   "assumed": 0,
   "checks": []
  },
  {
   "key": "m3",
   "number": "2b",
   "name": "Modul 2b",
   "end": false,
   "at": [
    2400.0,
    350.0
   ],
   "angle": -0.0,
   "outline": [
    [
     2400.0,
     350.0
    ],
    [
     3900.0,
     350.0
    ],
    [
     3900.0,
     700.0
    ],
    [
     2400.0,
     700.0
    ]
   ],
   "shape": {
    "kind": "straight",
    "length": 1500.0,
    "width": 350.0
   },
   "standard": "1500 × 350",
   "gables": [
    {
     "end": "A",
     "norm": null,
     "profile": null,
     "tracks": [
      100.0
     ]
    },
    {
     "end": "B",
     "norm": null,
     "profile": null,
     "tracks": []
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
       100.0
      ],
      "gable": "A",
      "track": 1
     },
     {
      "id": "n2",
      "type": "buffer_stop",
      "at": [
       1200.0,
       100.0
      ],
      "gable": null,
      "track": null
     }
    ],
    "pieces": [
     {
      "id": "s3",
      "start": "n1",
      "end": "n2",
      "segments": [
       {
        "kind": "line",
        "start": [
         0.0,
         100.0
        ],
        "end": [
         1200.0,
         100.0
        ]
       }
      ],
      "track": "4",
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "169"
      }
     }
    ],
    "switches": [],
    "labels": [],
    "symbols": [],
    "complete": true,
    "issued": 3
   },
   "switches": 0,
   "assumed": 0,
   "checks": []
  },
  {
   "key": "m4",
   "number": "3",
   "name": "Modul 3",
   "end": false,
   "at": [
    3900.0,
    0.0
   ],
   "angle": -0.0,
   "outline": [
    [
     3900.0,
     0.0
    ],
    [
     5400.0,
     0.0
    ],
    [
     5400.0,
     700.0
    ],
    [
     3900.0,
     700.0
    ]
   ],
   "shape": {
    "kind": "straight",
    "length": 1500.0,
    "width": 700.0
   },
   "standard": "1500 × 700",
   "gables": [
    {
     "end": "A",
     "norm": null,
     "profile": null,
     "tracks": [
      140.0,
      197.0
     ]
    },
    {
     "end": "B",
     "norm": null,
     "profile": null,
     "tracks": [
      140.0,
      197.0
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
       140.0
      ],
      "gable": "A",
      "track": 1
     },
     {
      "id": "n2",
      "type": "module_joint",
      "at": [
       0.0,
       197.0
      ],
      "gable": "A",
      "track": 2
     },
     {
      "id": "n3",
      "type": "switch",
      "at": [
       100.0,
       140.0
      ],
      "gable": null,
      "track": null
     },
     {
      "id": "n4",
      "type": "joint",
      "at": [
       459.317,
       140.0
      ],
      "gable": null,
      "track": null
     },
     {
      "id": "n5",
      "type": "joint",
      "at": [
       459.317,
       169.541
      ],
      "gable": null,
      "track": null
     },
     {
      "id": "n6",
      "type": "crossing",
      "at": [
       625.183,
       197.0
      ],
      "gable": null,
      "track": null
     },
     {
      "id": "n7",
      "type": "buffer_stop",
      "at": [
       794.752,
       225.072
      ],
      "gable": null,
      "track": null
     },
     {
      "id": "n8",
      "type": "switch",
      "at": [
       900.0,
       197.0
      ],
      "gable": null,
      "track": null
     },
     {
      "id": "n9",
      "type": "buffer_stop",
      "at": [
       1400.0,
       300.0
      ],
      "gable": null,
      "track": null
     },
     {
      "id": "n10",
      "type": "module_joint",
      "at": [
       1500.0,
       140.0
      ],
      "gable": "B",
      "track": 1
     },
     {
      "id": "n11",
      "type": "module_joint",
      "at": [
       1500.0,
       197.0
      ],
      "gable": "B",
      "track": 2
     }
    ],
    "pieces": [
     {
      "id": "s12",
      "start": "n1",
      "end": "n3",
      "segments": [
       {
        "kind": "line",
        "start": [
         0.0,
         140.0
        ],
        "end": [
         100.0,
         140.0
        ]
       }
      ],
      "track": "2",
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "153"
      }
     },
     {
      "id": "s13",
      "start": "n2",
      "end": "n6",
      "segments": [
       {
        "kind": "line",
        "start": [
         0.0,
         197.0
        ],
        "end": [
         625.183,
         197.0
        ]
       }
      ],
      "track": "3",
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "163"
      }
     },
     {
      "id": "s14",
      "start": "n3",
      "end": "n4",
      "segments": [
       {
        "kind": "line",
        "start": [
         100.0,
         140.0
        ],
        "end": [
         459.317,
         140.0
        ]
       }
      ],
      "track": null,
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "154"
      }
     },
     {
      "id": "s15",
      "start": "n3",
      "end": "n5",
      "segments": [
       {
        "kind": "arc",
        "start": [
         100.0,
         140.0
        ],
        "end": [
         459.317,
         169.541
        ],
        "center": [
         100.003,
         2339.982
        ],
        "radius": 2199.982,
        "clockwise": true
       }
      ],
      "track": null,
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "154"
      }
     },
     {
      "id": "s16",
      "start": "n4",
      "end": "n10",
      "segments": [
       {
        "kind": "line",
        "start": [
         459.317,
         140.0
        ],
        "end": [
         1500.0,
         140.0
        ]
       }
      ],
      "track": null,
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "155"
      }
     },
     {
      "id": "s17",
      "start": "n5",
      "end": "n6",
      "segments": [
       {
        "kind": "line",
        "start": [
         459.317,
         169.541
        ],
        "end": [
         625.183,
         197.0
        ]
       }
      ],
      "track": null,
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "172"
      }
     },
     {
      "id": "s18",
      "start": "n6",
      "end": "n7",
      "segments": [
       {
        "kind": "line",
        "start": [
         625.183,
         197.0
        ],
        "end": [
         794.752,
         225.072
        ]
       }
      ],
      "track": null,
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "172"
      }
     },
     {
      "id": "s19",
      "start": "n6",
      "end": "n8",
      "segments": [
       {
        "kind": "line",
        "start": [
         625.183,
         197.0
        ],
        "end": [
         900.0,
         197.0
        ]
       }
      ],
      "track": null,
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "163"
      }
     },
     {
      "id": "s20",
      "start": "n8",
      "end": "n11",
      "segments": [
       {
        "kind": "line",
        "start": [
         900.0,
         197.0
        ],
        "end": [
         1500.0,
         197.0
        ]
       }
      ],
      "track": null,
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "164"
      }
     },
     {
      "id": "s21",
      "start": "n8",
      "end": "n9",
      "segments": [
       {
        "kind": "arc",
        "start": [
         900.0,
         197.0
        ],
        "end": [
         967.648,
         201.121
        ],
        "center": [
         900.0,
         754.224
        ],
        "radius": 557.224,
        "clockwise": true
       },
       {
        "kind": "arc",
        "start": [
         967.648,
         201.121
        ],
        "end": [
         1034.375,
         213.094
        ],
        "center": [
         893.903,
         804.078
        ],
        "radius": 607.45,
        "clockwise": true
       },
       {
        "kind": "arc",
        "start": [
         1034.375,
         213.094
        ],
        "end": [
         1092.597,
         229.383
        ],
        "center": [
         857.081,
         958.99
        ],
        "radius": 766.677,
        "clockwise": true
       },
       {
        "kind": "arc",
        "start": [
         1092.597,
         229.383
        ],
        "end": [
         1150.0,
         248.5
        ],
        "center": [
         87.078,
         3344.388
        ],
        "radius": 3273.275,
        "clockwise": true
       },
       {
        "kind": "arc",
        "start": [
         1150.0,
         248.5
        ],
        "end": [
         1207.403,
         267.617
        ],
        "center": [
         2212.922,
         -2847.388
        ],
        "radius": 3273.275,
        "clockwise": false
       },
       {
        "kind": "arc",
        "start": [
         1207.403,
         267.617
        ],
        "end": [
         1265.625,
         283.906
        ],
        "center": [
         1442.919,
         -461.99
        ],
        "radius": 766.677,
        "clockwise": false
       },
       {
        "kind": "arc",
        "start": [
         1265.625,
         283.906
        ],
        "end": [
         1332.352,
         295.879
        ],
        "center": [
         1406.097,
         -307.078
        ],
        "radius": 607.45,
        "clockwise": false
       },
       {
        "kind": "arc",
        "start": [
         1332.352,
         295.879
        ],
        "end": [
         1400.0,
         300.0
        ],
        "center": [
         1400.0,
         -257.224
        ],
        "radius": 557.224,
        "clockwise": false
       }
      ],
      "track": null,
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "173"
      }
     }
    ],
    "switches": [
     {
      "id": "v22",
      "node": "n3",
      "type": "ordinary",
      "trunk": "s12",
      "straight": "s14",
      "diverging": "s15",
      "radius": 2200.0,
      "angle": 9.4,
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "154"
      },
      "number": "3",
      "design": null,
      "toward": "B",
      "locked": false
     },
     {
      "id": "v23",
      "node": "n8",
      "type": "ordinary",
      "trunk": "s19",
      "straight": "s20",
      "diverging": "s21",
      "radius": 557.2,
      "angle": null,
      "origin": {
       "source": "anyrail",
       "certainty": "uncertain",
       "ref": null
      },
      "number": "4",
      "design": null,
      "toward": "B",
      "locked": false
     }
    ],
    "labels": [],
    "symbols": [],
    "complete": true,
    "issued": 23
   },
   "switches": 2,
   "assumed": 1,
   "checks": [
    {
     "key": "switch_assumed:anyrail:v23",
     "kind": "switch_assumed",
     "source": "code",
     "at": [
      900.0,
      197.0
     ],
     "title": "Växel 4 är antagen",
     "text": "I AnyRail delar sig spåret här utan någon växel. Bekräfta att det är en växel, eller välj växeltyp.",
     "refs": [
      "v23",
      "n8"
     ],
     "choices": [
      {
       "id": "vaxel",
       "text": "Det är en växel",
       "closes": true,
       "action": null
      },
      {
       "id": "valj-typ",
       "text": "Välj växeltyp",
       "closes": false,
       "action": "design"
      }
     ],
     "answer": null,
     "assumed": true
    }
   ]
  },
  {
   "key": "m5",
   "number": "Ä1",
   "name": "Ändmodul Ä1",
   "end": true,
   "at": [
    200.0,
    0.0
   ],
   "angle": -0.0,
   "outline": [
    [
     200.0,
     0.0
    ],
    [
     900.0,
     0.0
    ],
    [
     900.0,
     355.0
    ],
    [
     200.0,
     355.0
    ]
   ],
   "shape": {
    "kind": "straight",
    "length": 700.0,
    "width": 355.0
   },
   "standard": "700 × 355",
   "gables": [
    {
     "end": "A",
     "norm": null,
     "profile": null,
     "tracks": [
      140.0,
      197.0
     ]
    },
    {
     "end": "B",
     "norm": null,
     "profile": null,
     "tracks": [
      140.0,
      197.0
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
       140.0
      ],
      "gable": "A",
      "track": 1
     },
     {
      "id": "n2",
      "type": "module_joint",
      "at": [
       0.0,
       197.0
      ],
      "gable": "A",
      "track": 2
     },
     {
      "id": "n3",
      "type": "module_joint",
      "at": [
       700.0,
       140.0
      ],
      "gable": "B",
      "track": 1
     },
     {
      "id": "n4",
      "type": "module_joint",
      "at": [
       700.0,
       197.0
      ],
      "gable": "B",
      "track": 2
     }
    ],
    "pieces": [
     {
      "id": "s5",
      "start": "n1",
      "end": "n3",
      "segments": [
       {
        "kind": "line",
        "start": [
         0.0,
         140.0
        ],
        "end": [
         700.0,
         140.0
        ]
       }
      ],
      "track": null,
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "149"
      }
     },
     {
      "id": "s6",
      "start": "n2",
      "end": "n4",
      "segments": [
       {
        "kind": "line",
        "start": [
         0.0,
         197.0
        ],
        "end": [
         700.0,
         197.0
        ]
       }
      ],
      "track": null,
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "157"
      }
     }
    ],
    "switches": [],
    "labels": [],
    "symbols": [],
    "complete": true,
    "issued": 6
   },
   "switches": 0,
   "assumed": 0,
   "checks": []
  },
  {
   "key": "m6",
   "number": "Ä2",
   "name": "Ändmodul Ä2",
   "end": true,
   "at": [
    5400.0,
    0.0
   ],
   "angle": -0.0,
   "outline": [
    [
     5400.0,
     0.0
    ],
    [
     6100.0,
     0.0
    ],
    [
     6100.0,
     355.0
    ],
    [
     5400.0,
     355.0
    ]
   ],
   "shape": {
    "kind": "straight",
    "length": 700.0,
    "width": 355.0
   },
   "standard": "700 × 355",
   "gables": [
    {
     "end": "A",
     "norm": null,
     "profile": null,
     "tracks": [
      140.0,
      197.0
     ]
    },
    {
     "end": "B",
     "norm": null,
     "profile": null,
     "tracks": []
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
       140.0
      ],
      "gable": "A",
      "track": 1
     },
     {
      "id": "n2",
      "type": "module_joint",
      "at": [
       0.0,
       197.0
      ],
      "gable": "A",
      "track": 2
     },
     {
      "id": "n3",
      "type": "buffer_stop",
      "at": [
       650.0,
       140.0
      ],
      "gable": null,
      "track": null
     },
     {
      "id": "n4",
      "type": "buffer_stop",
      "at": [
       650.0,
       197.0
      ],
      "gable": null,
      "track": null
     }
    ],
    "pieces": [
     {
      "id": "s5",
      "start": "n1",
      "end": "n3",
      "segments": [
       {
        "kind": "line",
        "start": [
         0.0,
         140.0
        ],
        "end": [
         650.0,
         140.0
        ]
       }
      ],
      "track": null,
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "156"
      }
     },
     {
      "id": "s6",
      "start": "n2",
      "end": "n4",
      "segments": [
       {
        "kind": "line",
        "start": [
         0.0,
         197.0
        ],
        "end": [
         650.0,
         197.0
        ]
       }
      ],
      "track": null,
      "origin": {
       "source": "anyrail",
       "certainty": "probable",
       "ref": "165"
      }
     }
    ],
    "switches": [],
    "labels": [],
    "symbols": [],
    "complete": true,
    "issued": 6
   },
   "switches": 0,
   "assumed": 0,
   "checks": []
  }
 ],
 "switches": [
  {
   "number": 1,
   "anyrail": "159",
   "side": "right",
   "radius": 2200.0,
   "angle": 9.4,
   "module": "m1",
   "assumed": false,
   "over_joint": false,
   "at": [
    1100.0,
    197.0
   ],
   "confirm": null
  },
  {
   "number": 2,
   "anyrail": "151",
   "side": "left",
   "radius": 2200.0,
   "angle": 9.4,
   "module": "m1",
   "assumed": false,
   "over_joint": true,
   "at": [
    2250.0,
    140.0
   ],
   "confirm": null
  },
  {
   "number": 3,
   "anyrail": "154",
   "side": "right",
   "radius": 2200.0,
   "angle": 9.4,
   "module": "m4",
   "assumed": false,
   "over_joint": false,
   "at": [
    4000.0,
    140.0
   ],
   "confirm": null
  },
  {
   "number": 4,
   "anyrail": null,
   "side": "right",
   "radius": 557.2,
   "angle": null,
   "module": "m4",
   "assumed": true,
   "over_joint": false,
   "at": [
    4800.0,
    197.0
   ],
   "confirm": "switch_assumed:anyrail:v23"
  }
 ],
 "checks": [
  {
   "key": "drawing_fix:gap:149+150:10",
   "kind": "drawing_fix",
   "source": "code",
   "at": [
    900.0,
    140.0
   ],
   "title": "Glapp på 10,0 mm sammanfogat",
   "text": "Två spårändar möttes inte i ritningen. De pekade mot varandra och flyttades till mittpunkten.",
   "refs": [
    "149",
    "150"
   ],
   "choices": [
    {
     "id": "stammer",
     "text": "Det stämmer",
     "closes": true,
     "action": null
    }
   ],
   "answer": null,
   "assumed": false
  },
  {
   "key": "drawing_fix:gap:157+158:8",
   "kind": "drawing_fix",
   "source": "code",
   "at": [
    900.0,
    197.0
   ],
   "title": "Glapp på 8,0 mm sammanfogat",
   "text": "Två spårändar möttes inte i ritningen. De pekade mot varandra och flyttades till mittpunkten.",
   "refs": [
    "157",
    "158"
   ],
   "choices": [
    {
     "id": "stammer",
     "text": "Det stämmer",
     "closes": true,
     "action": null
    }
   ],
   "answer": null,
   "assumed": false
  },
  {
   "key": "loose_part:1:600",
   "kind": "loose_part",
   "source": "code",
   "at": [
    1300.0,
    1100.0
   ],
   "title": "Lös del, 0,60 m spår, togs inte med",
   "text": "Spåren hänger inte ihop med resten av anläggningen. De är en sidoritning eller ett utkast och tas inte med.",
   "refs": [],
   "choices": [
    {
     "id": "stammer",
     "text": "Det stämmer",
     "closes": true,
     "action": null
    }
   ],
   "answer": null,
   "assumed": false
  },
  {
   "key": "switch_joint:2",
   "kind": "switch_joint",
   "source": "code",
   "at": [
    2250.0,
    140.0
   ],
   "title": "Växel 2 ligger över en modulskarv",
   "text": "Växeln sträcker sig in i nästa modul. Den hör till modulen där tungspetsen ligger.",
   "refs": [
    "151"
   ],
   "choices": [
    {
     "id": "stammer",
     "text": "Det stämmer",
     "closes": true,
     "action": null
    }
   ],
   "answer": null,
   "assumed": false
  },
  {
   "key": "oblique_joint:204:3.9",
   "kind": "oblique_joint",
   "source": "code",
   "at": [
    2400.0,
    134.9
   ],
   "title": "Spåret korsar skarven 3,9° snett",
   "text": "Spåret går inte rakt genom gaveln. Kontrollera att gavlarna passar.",
   "refs": [],
   "choices": [
    {
     "id": "stammer",
     "text": "Det stämmer",
     "closes": true,
     "action": null
    }
   ],
   "answer": null,
   "assumed": false
  },
  {
   "key": "drawing_fix:gap:160+161:10",
   "kind": "drawing_fix",
   "source": "code",
   "at": [
    2400.0,
    197.0
   ],
   "title": "Glapp på 10,0 mm sammanfogat",
   "text": "Två spårändar möttes inte i ritningen. De pekade mot varandra och flyttades till mittpunkten.",
   "refs": [
    "160",
    "161"
   ],
   "choices": [
    {
     "id": "stammer",
     "text": "Det stämmer",
     "closes": true,
     "action": null
    }
   ],
   "answer": null,
   "assumed": false
  },
  {
   "key": "drawing_fix:gap:168+169:8",
   "kind": "drawing_fix",
   "source": "code",
   "at": [
    2400.0,
    450.0
   ],
   "title": "Glapp på 8,0 mm sammanfogat",
   "text": "Två spårändar möttes inte i ritningen. De pekade mot varandra och flyttades till mittpunkten.",
   "refs": [
    "168",
    "169"
   ],
   "choices": [
    {
     "id": "stammer",
     "text": "Det stämmer",
     "closes": true,
     "action": null
    }
   ],
   "answer": null,
   "assumed": false
  },
  {
   "key": "drawing_fix:overlap:152+153:30",
   "kind": "drawing_fix",
   "source": "code",
   "at": [
    3900.0,
    140.0
   ],
   "title": "Överlapp på 30,0 mm sammanfogat",
   "text": "Två spårändar möttes inte i ritningen. De pekade mot varandra och flyttades till mittpunkten.",
   "refs": [
    "152",
    "153"
   ],
   "choices": [
    {
     "id": "stammer",
     "text": "Det stämmer",
     "closes": true,
     "action": null
    }
   ],
   "answer": null,
   "assumed": false
  },
  {
   "key": "drawing_fix:backward:162:30",
   "kind": "drawing_fix",
   "source": "code",
   "at": [
    3900.0,
    197.0
   ],
   "title": "Bakåtbit på 3,0 cm togs bort",
   "text": "En kort flexbit pekade bakåt: ett överlapp i ritningen. Grannarna kopplades ihop och kortades till mittpunkten.",
   "refs": [
    "162"
   ],
   "choices": [
    {
     "id": "stammer",
     "text": "Det stämmer",
     "closes": true,
     "action": null
    }
   ],
   "answer": null,
   "assumed": false
  },
  {
   "key": "drawing_fix:smooth:162:0",
   "kind": "drawing_fix",
   "source": "code",
   "at": [
    3900.0,
    197.1
   ],
   "title": "Flexbågen ritades om, flytt 0,1 mm",
   "text": "Bågen var snävare än 400 mm. Den ritades om som en jämn kurva med AnyRails egna ändriktningar.",
   "refs": [
    "162"
   ],
   "choices": [
    {
     "id": "stammer",
     "text": "Det stämmer",
     "closes": true,
     "action": null
    }
   ],
   "answer": null,
   "assumed": false
  },
  {
   "key": "switch_assumed:anyrail:4",
   "kind": "switch_assumed",
   "source": "code",
   "at": [
    4800.0,
    197.0
   ],
   "title": "Växel 4 är antagen",
   "text": "Spåret delar sig utan någon växel i AnyRail. Bekräfta den innan modulen publiceras.",
   "refs": [],
   "choices": [
    {
     "id": "vaxel",
     "text": "Det är en växel",
     "closes": true,
     "action": null
    }
   ],
   "answer": null,
   "assumed": true
  },
  {
   "key": "drawing_fix:gap:155+156:6",
   "kind": "drawing_fix",
   "source": "code",
   "at": [
    5400.0,
    140.0
   ],
   "title": "Glapp på 6,0 mm sammanfogat",
   "text": "Två spårändar möttes inte i ritningen. De pekade mot varandra och flyttades till mittpunkten.",
   "refs": [
    "155",
    "156"
   ],
   "choices": [
    {
     "id": "stammer",
     "text": "Det stämmer",
     "closes": true,
     "action": null
    }
   ],
   "answer": null,
   "assumed": false
  },
  {
   "key": "drawing_fix:gap:164+165:8",
   "kind": "drawing_fix",
   "source": "code",
   "at": [
    5400.0,
    197.0
   ],
   "title": "Glapp på 8,0 mm sammanfogat",
   "text": "Två spårändar möttes inte i ritningen. De pekade mot varandra och flyttades till mittpunkten.",
   "refs": [
    "164",
    "165"
   ],
   "choices": [
    {
     "id": "stammer",
     "text": "Det stämmer",
     "closes": true,
     "action": null
    }
   ],
   "answer": null,
   "assumed": false
  },
  {
   "key": "removed:loop:166",
   "kind": "removed",
   "source": "code",
   "at": [
    6080.0,
    168.5
   ],
   "title": "Öglan togs bort",
   "text": "Två spår var bundna med en tvär båge. Bågen togs bort och spåren slutar där, som vanliga spårändar.",
   "refs": [
    "166"
   ],
   "choices": [
    {
     "id": "stammer",
     "text": "Det stämmer",
     "closes": true,
     "action": null
    }
   ],
   "answer": null,
   "assumed": false
  }
 ],
 "stats": {
  "parts": 74,
  "track_parts": 26,
  "modules": 6,
  "switches": 4,
  "assumed": 1,
  "crossings": 1,
  "switches_over_joint": 1,
  "backward_removed": 1,
  "gaps": 6,
  "overlaps": 1,
  "smoothed": 1,
  "loops_removed": 1,
  "bridges_removed": 0,
  "walls_removed": 0,
  "doubled_removed": 0,
  "loose": 1,
  "side_drawings": 0,
  "max_kink": 1.01,
  "min_radius": 557.0,
  "station_tracks": 4,
  "station_middle": 2785.0,
  "arcs": 4,
  "arcs_other_way": 2
 },
 "graph": {
  "geometry": "mm",
  "nodes": [
   {
    "id": "n146",
    "type": "joint",
    "at": [
     900.0,
     140.0
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n148",
    "type": "switch",
    "at": [
     2250.0,
     140.0
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n150",
    "type": "joint",
    "at": [
     2609.317,
     140.0
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n151",
    "type": "joint",
    "at": [
     2609.317,
     110.459
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n153",
    "type": "joint",
    "at": [
     3900.0,
     140.0
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n155",
    "type": "switch",
    "at": [
     4000.0,
     140.0
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n157",
    "type": "joint",
    "at": [
     4359.317,
     140.0
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n158",
    "type": "joint",
    "at": [
     4359.317,
     169.541
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n160",
    "type": "joint",
    "at": [
     5400.0,
     140.0
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n162",
    "type": "buffer_stop",
    "at": [
     6050.0,
     140.0
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n164",
    "type": "joint",
    "at": [
     900.0,
     197.0
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n166",
    "type": "switch",
    "at": [
     1100.0,
     197.0
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n168",
    "type": "joint",
    "at": [
     1459.317,
     197.0
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n169",
    "type": "joint",
    "at": [
     1459.317,
     226.541
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n171",
    "type": "joint",
    "at": [
     2400.0,
     197.0
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n173",
    "type": "joint",
    "at": [
     3900.0,
     197.0
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n177",
    "type": "switch",
    "at": [
     4800.0,
     197.0
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n179",
    "type": "joint",
    "at": [
     5400.0,
     197.0
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n181",
    "type": "buffer_stop",
    "at": [
     6050.0,
     197.0
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n185",
    "type": "joint",
    "at": [
     2300.0,
     450.0
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n187",
    "type": "joint",
    "at": [
     2400.0,
     450.0
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n189",
    "type": "buffer_stop",
    "at": [
     3600.0,
     450.0
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n191",
    "type": "joint",
    "at": [
     2968.634,
     80.918
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n193",
    "type": "buffer_stop",
    "at": [
     3300.0,
     80.918
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n195",
    "type": "buffer_stop",
    "at": [
     4694.752,
     225.072
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n197",
    "type": "buffer_stop",
    "at": [
     5300.0,
     300.0
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n200",
    "type": "crossing",
    "at": [
     4525.183,
     197.0
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n202",
    "type": "buffer_stop",
    "at": [
     200.0,
     140.0
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n203",
    "type": "joint",
    "at": [
     2400.0,
     140.0
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n204",
    "type": "joint",
    "at": [
     2400.0,
     134.881
    ],
    "gable": null,
    "track": null
   },
   {
    "id": "n205",
    "type": "buffer_stop",
    "at": [
     200.0,
     197.0
    ],
    "gable": null,
    "track": null
   }
  ],
  "pieces": [
   {
    "id": "s2",
    "start": "n146",
    "end": "n148",
    "segments": [
     {
      "kind": "line",
      "start": [
       900.0,
       140.0
      ],
      "end": [
       2250.0,
       140.0
      ]
     }
    ],
    "track": null,
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "150"
    }
   },
   {
    "id": "s3",
    "start": "n148",
    "end": "n203",
    "segments": [
     {
      "kind": "line",
      "start": [
       2250.0,
       140.0
      ],
      "end": [
       2400.0,
       140.0
      ]
     }
    ],
    "track": "2",
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "151"
    }
   },
   {
    "id": "s4",
    "start": "n148",
    "end": "n204",
    "segments": [
     {
      "kind": "arc",
      "start": [
       2250.0,
       140.0
      ],
      "end": [
       2400.0,
       134.881
      ],
      "center": [
       2250.003,
       -2059.982
      ],
      "radius": 2199.982,
      "clockwise": false
     }
    ],
    "track": "1",
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "151"
    }
   },
   {
    "id": "s5",
    "start": "n150",
    "end": "n153",
    "segments": [
     {
      "kind": "line",
      "start": [
       2609.317,
       140.0
      ],
      "end": [
       3900.0,
       140.0
      ]
     }
    ],
    "track": "2",
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "152"
    }
   },
   {
    "id": "s6",
    "start": "n153",
    "end": "n155",
    "segments": [
     {
      "kind": "line",
      "start": [
       3900.0,
       140.0
      ],
      "end": [
       4000.0,
       140.0
      ]
     }
    ],
    "track": "2",
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "153"
    }
   },
   {
    "id": "s7",
    "start": "n155",
    "end": "n157",
    "segments": [
     {
      "kind": "line",
      "start": [
       4000.0,
       140.0
      ],
      "end": [
       4359.317,
       140.0
      ]
     }
    ],
    "track": null,
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "154"
    }
   },
   {
    "id": "s8",
    "start": "n155",
    "end": "n158",
    "segments": [
     {
      "kind": "arc",
      "start": [
       4000.0,
       140.0
      ],
      "end": [
       4359.317,
       169.541
      ],
      "center": [
       4000.003,
       2339.982
      ],
      "radius": 2199.982,
      "clockwise": true
     }
    ],
    "track": null,
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "154"
    }
   },
   {
    "id": "s9",
    "start": "n157",
    "end": "n160",
    "segments": [
     {
      "kind": "line",
      "start": [
       4359.317,
       140.0
      ],
      "end": [
       5400.0,
       140.0
      ]
     }
    ],
    "track": null,
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "155"
    }
   },
   {
    "id": "s10",
    "start": "n160",
    "end": "n162",
    "segments": [
     {
      "kind": "line",
      "start": [
       5400.0,
       140.0
      ],
      "end": [
       6050.0,
       140.0
      ]
     }
    ],
    "track": null,
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "156"
    }
   },
   {
    "id": "s12",
    "start": "n164",
    "end": "n166",
    "segments": [
     {
      "kind": "line",
      "start": [
       900.0,
       197.0
      ],
      "end": [
       1100.0,
       197.0
      ]
     }
    ],
    "track": null,
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "158"
    }
   },
   {
    "id": "s13",
    "start": "n166",
    "end": "n168",
    "segments": [
     {
      "kind": "line",
      "start": [
       1100.0,
       197.0
      ],
      "end": [
       1459.317,
       197.0
      ]
     }
    ],
    "track": "3",
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "159"
    }
   },
   {
    "id": "s14",
    "start": "n166",
    "end": "n169",
    "segments": [
     {
      "kind": "arc",
      "start": [
       1100.0,
       197.0
      ],
      "end": [
       1459.317,
       226.541
      ],
      "center": [
       1100.003,
       2396.982
      ],
      "radius": 2199.982,
      "clockwise": true
     }
    ],
    "track": "4",
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "159"
    }
   },
   {
    "id": "s15",
    "start": "n168",
    "end": "n171",
    "segments": [
     {
      "kind": "line",
      "start": [
       1459.317,
       197.0
      ],
      "end": [
       2400.0,
       197.0
      ]
     }
    ],
    "track": "3",
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "160"
    }
   },
   {
    "id": "s16",
    "start": "n171",
    "end": "n173",
    "segments": [
     {
      "kind": "line",
      "start": [
       2400.0,
       197.0
      ],
      "end": [
       3900.0,
       197.0
      ]
     }
    ],
    "track": "3",
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "161"
    }
   },
   {
    "id": "s18",
    "start": "n173",
    "end": "n200",
    "segments": [
     {
      "kind": "line",
      "start": [
       3900.0,
       197.0
      ],
      "end": [
       4525.183,
       197.0
      ]
     }
    ],
    "track": "3",
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "163"
    }
   },
   {
    "id": "s19",
    "start": "n177",
    "end": "n179",
    "segments": [
     {
      "kind": "line",
      "start": [
       4800.0,
       197.0
      ],
      "end": [
       5400.0,
       197.0
      ]
     }
    ],
    "track": null,
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "164"
    }
   },
   {
    "id": "s20",
    "start": "n179",
    "end": "n181",
    "segments": [
     {
      "kind": "line",
      "start": [
       5400.0,
       197.0
      ],
      "end": [
       6050.0,
       197.0
      ]
     }
    ],
    "track": null,
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "165"
    }
   },
   {
    "id": "s22",
    "start": "n169",
    "end": "n185",
    "segments": [
     {
      "kind": "arc",
      "start": [
       1459.317,
       226.541
      ],
      "end": [
       1511.559,
       236.663
      ],
      "center": [
       1300.205,
       1187.644
      ],
      "radius": 974.185,
      "clockwise": true
     },
     {
      "kind": "arc",
      "start": [
       1511.559,
       236.663
      ],
      "end": [
       1563.267,
       249.273
      ],
      "center": [
       1229.987,
       1503.584
      ],
      "radius": 1297.833,
      "clockwise": true
     },
     {
      "kind": "arc",
      "start": [
       1563.267,
       249.273
      ],
      "end": [
       1615.784,
       264.234
      ],
      "center": [
       1169.771,
       1730.21
      ],
      "radius": 1532.323,
      "clockwise": true
     },
     {
      "kind": "arc",
      "start": [
       1615.784,
       264.234
      ],
      "end": [
       1667.837,
       280.75
      ],
      "center": [
       947.606,
       2460.435
      ],
      "radius": 2295.596,
      "clockwise": true
     },
     {
      "kind": "arc",
      "start": [
       1667.837,
       280.75
      ],
      "end": [
       1773.255,
       317.468
      ],
      "center": [
       575.643,
       3586.132
      ],
      "radius": 3481.155,
      "clockwise": true
     },
     {
      "kind": "arc",
      "start": [
       1773.255,
       317.468
      ],
      "end": [
       1878.249,
       355.42
      ],
      "center": [
       6194.575,
       -11749.716
      ],
      "radius": 12851.653,
      "clockwise": false
     },
     {
      "kind": "arc",
      "start": [
       1878.249,
       355.42
      ],
      "end": [
       1930.869,
       373.836
      ],
      "center": [
       3474.033,
       -4119.956
      ],
      "radius": 4751.37,
      "clockwise": false
     },
     {
      "kind": "arc",
      "start": [
       1930.869,
       373.836
      ],
      "end": [
       1983.792,
       391.354
      ],
      "center": [
       2745.413,
       -1998.167
      ],
      "radius": 2507.963,
      "clockwise": false
     },
     {
      "kind": "arc",
      "start": [
       1983.792,
       391.354
      ],
      "end": [
       2036.331,
       407.312
      ],
      "center": [
       2593.798,
       -1522.489
      ],
      "radius": 2008.707,
      "clockwise": false
     },
     {
      "kind": "arc",
      "start": [
       2036.331,
       407.312
      ],
      "end": [
       2089.365,
       421.516
      ],
      "center": [
       2426.149,
       -942.132
      ],
      "radius": 1404.62,
      "clockwise": false
     },
     {
      "kind": "arc",
      "start": [
       2089.365,
       421.516
      ],
      "end": [
       2141.83,
       433.242
      ],
      "center": [
       2379.229,
       -752.153
      ],
      "radius": 1208.933,
      "clockwise": false
     },
     {
      "kind": "arc",
      "start": [
       2141.83,
       433.242
      ],
      "end": [
       2194.816,
       442.274
      ],
      "center": [
       2324.989,
       -481.32
      ],
      "radius": 932.723,
      "clockwise": false
     },
     {
      "kind": "arc",
      "start": [
       2194.816,
       442.274
      ],
      "end": [
       2247.279,
       447.979
      ],
      "center": [
       2311.012,
       -382.15
      ],
      "radius": 832.572,
      "clockwise": false
     },
     {
      "kind": "arc",
      "start": [
       2247.279,
       447.979
      ],
      "end": [
       2300.0,
       450.0
      ],
      "center": [
       2300.0,
       -238.717
      ],
      "radius": 688.717,
      "clockwise": false
     }
    ],
    "track": "4",
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "167"
    }
   },
   {
    "id": "s23",
    "start": "n185",
    "end": "n187",
    "segments": [
     {
      "kind": "line",
      "start": [
       2300.0,
       450.0
      ],
      "end": [
       2400.0,
       450.0
      ]
     }
    ],
    "track": "4",
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "168"
    }
   },
   {
    "id": "s24",
    "start": "n187",
    "end": "n189",
    "segments": [
     {
      "kind": "line",
      "start": [
       2400.0,
       450.0
      ],
      "end": [
       3600.0,
       450.0
      ]
     }
    ],
    "track": "4",
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "169"
    }
   },
   {
    "id": "s25",
    "start": "n151",
    "end": "n191",
    "segments": [
     {
      "kind": "arc",
      "start": [
       2609.317,
       110.459
      ],
      "end": [
       2968.634,
       80.918
      ],
      "center": [
       2968.631,
       2280.9
      ],
      "radius": 2199.982,
      "clockwise": true
     }
    ],
    "track": "1",
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "170"
    }
   },
   {
    "id": "s26",
    "start": "n191",
    "end": "n193",
    "segments": [
     {
      "kind": "line",
      "start": [
       2968.634,
       80.918
      ],
      "end": [
       3300.0,
       80.918
      ]
     }
    ],
    "track": "1",
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "171"
    }
   },
   {
    "id": "s27",
    "start": "n158",
    "end": "n200",
    "segments": [
     {
      "kind": "line",
      "start": [
       4359.317,
       169.541
      ],
      "end": [
       4525.183,
       197.0
      ]
     }
    ],
    "track": null,
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "172"
    }
   },
   {
    "id": "s28",
    "start": "n177",
    "end": "n197",
    "segments": [
     {
      "kind": "arc",
      "start": [
       4800.0,
       197.0
      ],
      "end": [
       4867.648,
       201.121
      ],
      "center": [
       4800.0,
       754.224
      ],
      "radius": 557.224,
      "clockwise": true
     },
     {
      "kind": "arc",
      "start": [
       4867.648,
       201.121
      ],
      "end": [
       4934.375,
       213.094
      ],
      "center": [
       4793.903,
       804.078
      ],
      "radius": 607.45,
      "clockwise": true
     },
     {
      "kind": "arc",
      "start": [
       4934.375,
       213.094
      ],
      "end": [
       4992.597,
       229.383
      ],
      "center": [
       4757.081,
       958.99
      ],
      "radius": 766.677,
      "clockwise": true
     },
     {
      "kind": "arc",
      "start": [
       4992.597,
       229.383
      ],
      "end": [
       5050.0,
       248.5
      ],
      "center": [
       3987.078,
       3344.388
      ],
      "radius": 3273.275,
      "clockwise": true
     },
     {
      "kind": "arc",
      "start": [
       5050.0,
       248.5
      ],
      "end": [
       5107.403,
       267.617
      ],
      "center": [
       6112.922,
       -2847.388
      ],
      "radius": 3273.275,
      "clockwise": false
     },
     {
      "kind": "arc",
      "start": [
       5107.403,
       267.617
      ],
      "end": [
       5165.625,
       283.906
      ],
      "center": [
       5342.919,
       -461.99
      ],
      "radius": 766.677,
      "clockwise": false
     },
     {
      "kind": "arc",
      "start": [
       5165.625,
       283.906
      ],
      "end": [
       5232.352,
       295.879
      ],
      "center": [
       5306.097,
       -307.078
      ],
      "radius": 607.45,
      "clockwise": false
     },
     {
      "kind": "arc",
      "start": [
       5232.352,
       295.879
      ],
      "end": [
       5300.0,
       300.0
      ],
      "center": [
       5300.0,
       -257.224
      ],
      "radius": 557.224,
      "clockwise": false
     }
    ],
    "track": null,
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "173"
    }
   },
   {
    "id": "s30",
    "start": "n200",
    "end": "n195",
    "segments": [
     {
      "kind": "line",
      "start": [
       4525.183,
       197.0
      ],
      "end": [
       4694.752,
       225.072
      ]
     }
    ],
    "track": null,
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "172"
    }
   },
   {
    "id": "s31",
    "start": "n200",
    "end": "n177",
    "segments": [
     {
      "kind": "line",
      "start": [
       4525.183,
       197.0
      ],
      "end": [
       4800.0,
       197.0
      ]
     }
    ],
    "track": null,
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "163"
    }
   },
   {
    "id": "s32",
    "start": "n202",
    "end": "n146",
    "segments": [
     {
      "kind": "line",
      "start": [
       200.0,
       140.0
      ],
      "end": [
       900.0,
       140.0
      ]
     }
    ],
    "track": null,
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "149"
    }
   },
   {
    "id": "s33",
    "start": "n203",
    "end": "n150",
    "segments": [
     {
      "kind": "line",
      "start": [
       2400.0,
       140.0
      ],
      "end": [
       2609.317,
       140.0
      ]
     }
    ],
    "track": "2",
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "151"
    }
   },
   {
    "id": "s34",
    "start": "n204",
    "end": "n151",
    "segments": [
     {
      "kind": "arc",
      "start": [
       2400.0,
       134.881
      ],
      "end": [
       2609.317,
       110.459
      ],
      "center": [
       2250.003,
       -2059.982
      ],
      "radius": 2199.982,
      "clockwise": false
     }
    ],
    "track": "1",
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "151"
    }
   },
   {
    "id": "s35",
    "start": "n205",
    "end": "n164",
    "segments": [
     {
      "kind": "line",
      "start": [
       200.0,
       197.0
      ],
      "end": [
       900.0,
       197.0
      ]
     }
    ],
    "track": null,
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "157"
    }
   }
  ],
  "switches": [
   {
    "id": "v1",
    "node": "n166",
    "type": "ordinary",
    "trunk": "s12",
    "straight": "s13",
    "diverging": "s14",
    "radius": 2200.0,
    "angle": 9.4,
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "159"
    },
    "number": "1",
    "design": null,
    "toward": null,
    "locked": false
   },
   {
    "id": "v2",
    "node": "n148",
    "type": "ordinary",
    "trunk": "s2",
    "straight": "s3",
    "diverging": "s4",
    "radius": 2200.0,
    "angle": 9.4,
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "151"
    },
    "number": "2",
    "design": null,
    "toward": null,
    "locked": false
   },
   {
    "id": "v3",
    "node": "n155",
    "type": "ordinary",
    "trunk": "s6",
    "straight": "s7",
    "diverging": "s8",
    "radius": 2200.0,
    "angle": 9.4,
    "origin": {
     "source": "anyrail",
     "certainty": "probable",
     "ref": "154"
    },
    "number": "3",
    "design": null,
    "toward": null,
    "locked": false
   },
   {
    "id": "v4",
    "node": "n177",
    "type": "ordinary",
    "trunk": "s31",
    "straight": "s19",
    "diverging": "s28",
    "radius": 557.2,
    "angle": null,
    "origin": {
     "source": "anyrail",
     "certainty": "uncertain",
     "ref": null
    },
    "number": "4",
    "design": null,
    "toward": null,
    "locked": false
   }
  ],
  "labels": [],
  "symbols": [],
  "complete": true,
  "issued": 0
 },
 "drawing": [
  [
   [
    230.0,
    0.0
   ],
   [
    870.0,
    0.0
   ]
  ],
  [
   [
    900.0,
    30.0
   ],
   [
    900.0,
    325.0
   ]
  ],
  [
   [
    870.0,
    355.0
   ],
   [
    230.0,
    355.0
   ]
  ],
  [
   [
    200.0,
    325.0
   ],
   [
    200.0,
    30.0
   ]
  ],
  [
   [
    170.0,
    0.0
   ],
   [
    230.0,
    0.0
   ]
  ],
  [
   [
    200.0,
    -30.0
   ],
   [
    200.0,
    30.0
   ]
  ],
  [
   [
    870.0,
    0.0
   ],
   [
    930.0,
    0.0
   ]
  ],
  [
   [
    900.0,
    -30.0
   ],
   [
    900.0,
    30.0
   ]
  ],
  [
   [
    870.0,
    355.0
   ],
   [
    930.0,
    355.0
   ]
  ],
  [
   [
    900.0,
    325.0
   ],
   [
    900.0,
    385.0
   ]
  ],
  [
   [
    170.0,
    355.0
   ],
   [
    230.0,
    355.0
   ]
  ],
  [
   [
    200.0,
    325.0
   ],
   [
    200.0,
    385.0
   ]
  ],
  [
   [
    930.0,
    0.0
   ],
   [
    2370.0,
    0.0
   ]
  ],
  [
   [
    2400.0,
    30.0
   ],
   [
    2400.0,
    670.0
   ]
  ],
  [
   [
    2370.0,
    700.0
   ],
   [
    930.0,
    700.0
   ]
  ],
  [
   [
    900.0,
    670.0
   ],
   [
    900.0,
    30.0
   ]
  ],
  [
   [
    870.0,
    0.0
   ],
   [
    930.0,
    0.0
   ]
  ],
  [
   [
    900.0,
    -30.0
   ],
   [
    900.0,
    30.0
   ]
  ],
  [
   [
    2370.0,
    0.0
   ],
   [
    2430.0,
    0.0
   ]
  ],
  [
   [
    2400.0,
    -30.0
   ],
   [
    2400.0,
    30.0
   ]
  ],
  [
   [
    2370.0,
    700.0
   ],
   [
    2430.0,
    700.0
   ]
  ],
  [
   [
    2400.0,
    670.0
   ],
   [
    2400.0,
    730.0
   ]
  ],
  [
   [
    870.0,
    700.0
   ],
   [
    930.0,
    700.0
   ]
  ],
  [
   [
    900.0,
    670.0
   ],
   [
    900.0,
    730.0
   ]
  ],
  [
   [
    2430.0,
    0.0
   ],
   [
    3870.0,
    0.0
   ]
  ],
  [
   [
    3900.0,
    30.0
   ],
   [
    3900.0,
    320.0
   ]
  ],
  [
   [
    3870.0,
    350.0
   ],
   [
    2430.0,
    350.0
   ]
  ],
  [
   [
    2400.0,
    320.0
   ],
   [
    2400.0,
    30.0
   ]
  ],
  [
   [
    2370.0,
    0.0
   ],
   [
    2430.0,
    0.0
   ]
  ],
  [
   [
    2400.0,
    -30.0
   ],
   [
    2400.0,
    30.0
   ]
  ],
  [
   [
    3870.0,
    0.0
   ],
   [
    3930.0,
    0.0
   ]
  ],
  [
   [
    3900.0,
    -30.0
   ],
   [
    3900.0,
    30.0
   ]
  ],
  [
   [
    3870.0,
    350.0
   ],
   [
    3930.0,
    350.0
   ]
  ],
  [
   [
    3900.0,
    320.0
   ],
   [
    3900.0,
    380.0
   ]
  ],
  [
   [
    2370.0,
    350.0
   ],
   [
    2430.0,
    350.0
   ]
  ],
  [
   [
    2400.0,
    320.0
   ],
   [
    2400.0,
    380.0
   ]
  ],
  [
   [
    2430.0,
    350.0
   ],
   [
    3870.0,
    350.0
   ]
  ],
  [
   [
    3900.0,
    380.0
   ],
   [
    3900.0,
    670.0
   ]
  ],
  [
   [
    3870.0,
    700.0
   ],
   [
    2430.0,
    700.0
   ]
  ],
  [
   [
    2400.0,
    670.0
   ],
   [
    2400.0,
    380.0
   ]
  ],
  [
   [
    2370.0,
    350.0
   ],
   [
    2430.0,
    350.0
   ]
  ],
  [
   [
    2400.0,
    320.0
   ],
   [
    2400.0,
    380.0
   ]
  ],
  [
   [
    3870.0,
    350.0
   ],
   [
    3930.0,
    350.0
   ]
  ],
  [
   [
    3900.0,
    320.0
   ],
   [
    3900.0,
    380.0
   ]
  ],
  [
   [
    3870.0,
    700.0
   ],
   [
    3930.0,
    700.0
   ]
  ],
  [
   [
    3900.0,
    670.0
   ],
   [
    3900.0,
    730.0
   ]
  ],
  [
   [
    2370.0,
    700.0
   ],
   [
    2430.0,
    700.0
   ]
  ],
  [
   [
    2400.0,
    670.0
   ],
   [
    2400.0,
    730.0
   ]
  ],
  [
   [
    3930.0,
    0.0
   ],
   [
    5370.0,
    0.0
   ]
  ],
  [
   [
    5400.0,
    30.0
   ],
   [
    5400.0,
    670.0
   ]
  ],
  [
   [
    5370.0,
    700.0
   ],
   [
    3930.0,
    700.0
   ]
  ],
  [
   [
    3900.0,
    670.0
   ],
   [
    3900.0,
    30.0
   ]
  ],
  [
   [
    3870.0,
    0.0
   ],
   [
    3930.0,
    0.0
   ]
  ],
  [
   [
    3900.0,
    -30.0
   ],
   [
    3900.0,
    30.0
   ]
  ],
  [
   [
    5370.0,
    0.0
   ],
   [
    5430.0,
    0.0
   ]
  ],
  [
   [
    5400.0,
    -30.0
   ],
   [
    5400.0,
    30.0
   ]
  ],
  [
   [
    5370.0,
    700.0
   ],
   [
    5430.0,
    700.0
   ]
  ],
  [
   [
    5400.0,
    670.0
   ],
   [
    5400.0,
    730.0
   ]
  ],
  [
   [
    3870.0,
    700.0
   ],
   [
    3930.0,
    700.0
   ]
  ],
  [
   [
    3900.0,
    670.0
   ],
   [
    3900.0,
    730.0
   ]
  ],
  [
   [
    5430.0,
    0.0
   ],
   [
    6070.0,
    0.0
   ]
  ],
  [
   [
    6100.0,
    30.0
   ],
   [
    6100.0,
    325.0
   ]
  ],
  [
   [
    6070.0,
    355.0
   ],
   [
    5430.0,
    355.0
   ]
  ],
  [
   [
    5400.0,
    325.0
   ],
   [
    5400.0,
    30.0
   ]
  ],
  [
   [
    5370.0,
    0.0
   ],
   [
    5430.0,
    0.0
   ]
  ],
  [
   [
    5400.0,
    -30.0
   ],
   [
    5400.0,
    30.0
   ]
  ],
  [
   [
    6070.0,
    0.0
   ],
   [
    6130.0,
    0.0
   ]
  ],
  [
   [
    6100.0,
    -30.0
   ],
   [
    6100.0,
    30.0
   ]
  ],
  [
   [
    6070.0,
    355.0
   ],
   [
    6130.0,
    355.0
   ]
  ],
  [
   [
    6100.0,
    325.0
   ],
   [
    6100.0,
    385.0
   ]
  ],
  [
   [
    5370.0,
    355.0
   ],
   [
    5430.0,
    355.0
   ]
  ],
  [
   [
    5400.0,
    325.0
   ],
   [
    5400.0,
    385.0
   ]
  ]
 ],
 "left_out": [
  [
   [
    6050.0,
    140.0
   ],
   [
    6067.7,
    144.8
   ],
   [
    6078.6,
    159.4
   ],
   [
    6078.6,
    177.6
   ],
   [
    6067.7,
    192.2
   ],
   [
    6050.0,
    197.0
   ]
  ],
  [
   [
    3915.0,
    197.0
   ],
   [
    3900.0,
    197.1
   ],
   [
    3885.0,
    197.0
   ]
  ],
  [
   [
    1000.0,
    1100.0
   ],
   [
    1020.0,
    1100.0
   ],
   [
    1040.0,
    1100.0
   ],
   [
    1060.0,
    1100.0
   ],
   [
    1080.0,
    1100.0
   ],
   [
    1100.0,
    1100.0
   ],
   [
    1120.0,
    1100.0
   ],
   [
    1140.0,
    1100.0
   ],
   [
    1160.0,
    1100.0
   ],
   [
    1180.0,
    1100.0
   ],
   [
    1200.0,
    1100.0
   ],
   [
    1220.0,
    1100.0
   ],
   [
    1240.0,
    1100.0
   ],
   [
    1260.0,
    1100.0
   ],
   [
    1280.0,
    1100.0
   ],
   [
    1300.0,
    1100.0
   ],
   [
    1320.0,
    1100.0
   ],
   [
    1340.0,
    1100.0
   ],
   [
    1360.0,
    1100.0
   ],
   [
    1380.0,
    1100.0
   ],
   [
    1400.0,
    1100.0
   ],
   [
    1420.0,
    1100.0
   ],
   [
    1440.0,
    1100.0
   ],
   [
    1460.0,
    1100.0
   ],
   [
    1480.0,
    1100.0
   ],
   [
    1500.0,
    1100.0
   ],
   [
    1520.0,
    1100.0
   ],
   [
    1540.0,
    1100.0
   ],
   [
    1560.0,
    1100.0
   ],
   [
    1580.0,
    1100.0
   ],
   [
    1600.0,
    1100.0
   ]
  ],
  [
   [
    100.0,
    140.0
   ],
   [
    120.0,
    140.0
   ],
   [
    140.0,
    140.0
   ],
   [
    160.0,
    140.0
   ],
   [
    180.0,
    140.0
   ],
   [
    200.0,
    140.0
   ]
  ],
  [
   [
    100.0,
    197.0
   ],
   [
    120.0,
    197.0
   ],
   [
    140.0,
    197.0
   ],
   [
    160.0,
    197.0
   ],
   [
    180.0,
    197.0
   ],
   [
    200.0,
    197.0
   ]
  ]
 ],
 "files": [
  {
   "name": "DXF, hela stationen",
   "file": "exempelstation-anlaggning.dxf",
   "url": "/api/cad/1/anyrail/5b0c2a1e-7d3f-4e60-9a81-2b3c4d5e6f70/files/anlaggning.dxf",
   "media_type": "application/dxf"
  },
  {
   "name": "Gavelprofiler (CSV)",
   "file": "exempelstation-gavelprofiler.csv",
   "url": "/api/cad/1/anyrail/5b0c2a1e-7d3f-4e60-9a81-2b3c4d5e6f70/files/gavelprofiler.csv",
   "media_type": "text/csv; charset=utf-8"
  },
  {
   "name": "Växellista (CSV)",
   "file": "exempelstation-vaxlar.csv",
   "url": "/api/cad/1/anyrail/5b0c2a1e-7d3f-4e60-9a81-2b3c4d5e6f70/files/vaxlar.csv",
   "media_type": "text/csv; charset=utf-8"
  },
  {
   "name": "DXF, modul 1",
   "file": "exempelstation-modul-1.dxf",
   "url": "/api/cad/1/anyrail/5b0c2a1e-7d3f-4e60-9a81-2b3c4d5e6f70/files/modul-m1.dxf",
   "media_type": "application/dxf"
  },
  {
   "name": "DXF, modul 2a",
   "file": "exempelstation-modul-2a.dxf",
   "url": "/api/cad/1/anyrail/5b0c2a1e-7d3f-4e60-9a81-2b3c4d5e6f70/files/modul-m2.dxf",
   "media_type": "application/dxf"
  },
  {
   "name": "DXF, modul 2b",
   "file": "exempelstation-modul-2b.dxf",
   "url": "/api/cad/1/anyrail/5b0c2a1e-7d3f-4e60-9a81-2b3c4d5e6f70/files/modul-m3.dxf",
   "media_type": "application/dxf"
  },
  {
   "name": "DXF, modul 3",
   "file": "exempelstation-modul-3.dxf",
   "url": "/api/cad/1/anyrail/5b0c2a1e-7d3f-4e60-9a81-2b3c4d5e6f70/files/modul-m4.dxf",
   "media_type": "application/dxf"
  },
  {
   "name": "DXF, modul Ä1",
   "file": "exempelstation-modul-a1.dxf",
   "url": "/api/cad/1/anyrail/5b0c2a1e-7d3f-4e60-9a81-2b3c4d5e6f70/files/modul-m5.dxf",
   "media_type": "application/dxf"
  },
  {
   "name": "DXF, modul Ä2",
   "file": "exempelstation-modul-a2.dxf",
   "url": "/api/cad/1/anyrail/5b0c2a1e-7d3f-4e60-9a81-2b3c4d5e6f70/files/modul-m6.dxf",
   "media_type": "application/dxf"
  }
 ],
 "created": null,
 "created_at": "2026-11-20T12:00:00Z"
};
