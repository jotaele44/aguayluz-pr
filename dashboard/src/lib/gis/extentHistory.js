// Mirrored from spiderweb-pr server/frontend/src/spatial/gis/extentHistory.ts (jotaele44/spiderweb-pr#435),
// transpiled to JavaScript for this JSX dashboard. Keep behaviour identical to the source;
// change the TypeScript original first, then re-mirror.
function same(a, b) {
    return (Math.abs(a.zoom - b.zoom) < 0.01 &&
        Math.abs(a.center[0] - b.center[0]) < 1e-6 &&
        Math.abs(a.center[1] - b.center[1]) < 1e-6);
}
export class ExtentHistory {
    limit;
    stack = [];
    index = -1;
    suppressNext = false;
    constructor(limit = 50) {
        this.limit = limit;
    }
    push(extent) {
        if (this.suppressNext) {
            this.suppressNext = false;
            return;
        }
        const current = this.stack[this.index];
        if (current && same(current, extent))
            return;
        this.stack = [...this.stack.slice(0, this.index + 1), extent].slice(-this.limit);
        this.index = this.stack.length - 1;
    }
    back() {
        if (!this.canBack)
            return null;
        this.index -= 1;
        this.suppressNext = true;
        return this.stack[this.index];
    }
    forward() {
        if (!this.canForward)
            return null;
        this.index += 1;
        this.suppressNext = true;
        return this.stack[this.index];
    }
    get canBack() {
        return this.index > 0;
    }
    get canForward() {
        return this.index >= 0 && this.index < this.stack.length - 1;
    }
}
