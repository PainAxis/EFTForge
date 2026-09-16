/* eslint-env node */
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

// Same vectors backend/tests/test_calculations.py checks stats.py::_calc_evo_ergo_delta
// against - a drift between the Python and JS copies of the EED/arm-stamina formula
// shows up as a failure here or there instead of a silent client/server stat mismatch.
const goldenPath = path.join(__dirname, "../../backend/tests/data/stat_formula_golden.json");
const golden = JSON.parse(fs.readFileSync(goldenPath, "utf8"));

const source = fs.readFileSync(path.join(__dirname, "../modules/calculations.js"), "utf8");

function loadCalc() {
    const EFTForge = {};
    const ctx = vm.createContext({ window: { EFTForge }, EFTForge });
    vm.runInContext(source, ctx);
    return ctx.EFTForge.calc;
}

test("calcEED matches the shared golden vectors", () => {
    const { calcEED } = loadCalc();
    for (const c of golden.cases) {
        const eed = calcEED(c.total_ergo, c.total_weight, c.equip_ergo_modifier);
        assert.ok(
            Math.abs(eed - c.expected_eed) < 0.01,
            `calcEED(${c.total_ergo}, ${c.total_weight}, ${c.equip_ergo_modifier}) = ${eed}, expected ${c.expected_eed}`
        );
    }
});

test("calcArmStamina matches the shared golden vectors", () => {
    const { calcArmStamina } = loadCalc();
    for (const c of golden.cases) {
        const stamina = calcArmStamina(c.total_weight, c.total_ergo, c.strength_level, c.equip_ergo_modifier);
        assert.ok(
            Math.abs(stamina - c.expected_arm_stamina) < 0.01,
            `calcArmStamina(${c.total_weight}, ${c.total_ergo}, ${c.strength_level}, ${c.equip_ergo_modifier}) = ${stamina}, expected ${c.expected_arm_stamina}`
        );
    }
});
