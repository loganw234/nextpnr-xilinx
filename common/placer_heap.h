/*
 *  nextpnr -- Next Generation Place and Route
 *
 *  Copyright (C) 2019  David Shah <david@symbioticeda.com>
 *
 *  Permission to use, copy, modify, and/or distribute this software for any
 *  purpose with or without fee is hereby granted, provided that the above
 *  copyright notice and this permission notice appear in all copies.
 *
 *  THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
 *  WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
 *  MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
 *  ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
 *  WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
 *  ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
 *  OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
 *
 *  [[cite]] HeAP
 *  Analytical Placement for Heterogeneous FPGAs, Marcel Gort and Jason H. Anderson
 *  https://janders.eecg.utoronto.ca/pdfs/marcelfpl12.pdf
 *
 *  [[cite]] SimPL
 *  SimPL: An Effective Placement Algorithm, Myung-Chul Kim, Dong-Jin Lee and Igor L. Markov
 *  http://www.ece.umich.edu/cse/awards/pdfs/iccad10-simpl.pdf
 */

#ifndef PLACER_HEAP_H
#define PLACER_HEAP_H
#include "log.h"
#include "nextpnr.h"

NEXTPNR_NAMESPACE_BEGIN

struct PlacerHeapCfg
{
    PlacerHeapCfg(Context *ctx);

    float alpha, beta;
    float criticalityExponent;
    float timingWeight;
    bool timing_driven;
    float solverTolerance;
    bool placeAllAtOnce;
    float netShareWeight;

    int hpwl_scale_x, hpwl_scale_y;
    int spread_scale_x, spread_scale_y;

    // [dense] How long the analytic loop runs, and which of its legal
    // placements it keeps. Upstream: stop after max_stall iterations
    // without a better legal wirelength (5), no minimum, keep the best.
    // keep_last keeps the final iteration's instead - the most converged,
    // not the shortest. Read from the environment (NEXTPNR_PLACER_MAX_STALL,
    // NEXTPNR_PLACER_MIN_ITER, NEXTPNR_PLACER_KEEP=best|last), as the base
    // reads its other HeAP knobs: a setting added before packing moves the
    // placement through name interning (dense/LEDGER.md, 2026-09-23), a
    // variable does not, so a run at the defaults places as upstream does.
    int max_stall = 5, min_iter = 0;
    bool keep_last = false;

    // [dense] Keep each block of the design together. A synthesised
    // netlist is flat, but most nets keep their RTL paths: a net whose name
    // has more than block_depth dot-separated components names the instance
    // its first block_depth components spell, and a cell belongs to the
    // instance its nets name most often (nets above 2000 users do not
    // vote). Each solved cell of a block of at least block_min cells is
    // then tied to the block's mean position by one more two-pin net of
    // weight block_weight, in the solver's own linearisation. 0 (the
    // default) is upstream. NEXTPNR_PLACER_BLOCK_WEIGHT / _DEPTH / _MIN.
    float block_weight = 0;
    int block_depth = 4, block_min = 200;
    // When the pull acts: from HeAP iteration block_from on (-1, the
    // default, is every solve, the initial ones included), rising to its
    // full weight over block_ramp iterations (0: at once).
    // NEXTPNR_PLACER_BLOCK_FROM / _RAMP. At the start every block's mean is
    // the mean of a random placement, near the chip's middle, and a pull
    // there gathers every block into one heap (2026-09-24, dense/LEDGER.md).
    int block_from = -1, block_ramp = 0;

    // These cell types will be randomly locked to prevent singular matrices
    std::unordered_set<IdString> ioBufTypes;
    // These cell types are part of the same unit (e.g. slices split into
    // components) so will always be spread together
    std::vector<std::unordered_set<IdString>> cellGroups;
};

extern bool placer_heap(Context *ctx, PlacerHeapCfg cfg);
NEXTPNR_NAMESPACE_END
#endif
