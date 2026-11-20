"""Bildkedjan: a module's track plan from a photo from above (#89 del c1, profile Modulfoto).

Code measures; AI only reads which tracks connect, with fixed answers (CAD2). The steps, in
the order the chain runs them:

- intake: the photo taken in, its metadata gone (step 2);
- corners, camera: the module's corners, the camera and the lens (steps 4 and 5);
- stitch: several photos of a long module as one (step 7);
- rectify: the module straightened to the rail plane, the light evened out (steps 6 and 8);
- measures: the quality gate, the gauge, the sleepers and the ± (steps 3 and 9);
- trackmap, paths, network: the tracks found, followed and joined (steps 10 and 11);
- questions, result: what AI is asked and what the owner is asked (steps 11 and 15);
- build: the geometry, piece by piece (step 12);
- chain: the whole, versioned and reproducible (step 16).

syntetisk renders modules with a known geometry, for the tests.
"""
