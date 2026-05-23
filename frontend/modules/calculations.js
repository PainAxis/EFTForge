window.EFTForge = window.EFTForge || {};

function calcArmStamina(weight, ergo) {
    return 233.65 / (weight + 0.83) + 0.185 * ergo + 23.16;
}

/**
 * Evo-Ergo Delta (EED) - measures how far the build's weight is from the
 * ergonomics-derived "ideal weight" threshold (KG).
 *
 * Formula reverse-engineered by SpaceMonkey37 from in-game data.
 *
 * @param {number} totalErgo   - total ergonomics of the equipped build
 * @param {number} totalWeight - total weight (kg) of the equipped build
 * @param {number} b           - equipment ergo modifier (0–1 decimal sum from headgear/armor/rig etc.)
 *
 * E  = ergo adjusted for equipment modifier
 * KG = polynomial fit of the ideal weight curve as a function of E
 *      coefficients: 0.0007556, 0.02736, 2.9159  (quadratic, from regression)
 * EED = -15 × (weight − KG): positive = under ideal weight (good), negative = overweight (bad)
 */
function calcEED(totalErgo, totalWeight, b = 0) {
    const E = totalErgo * (1 + b);
    const KG = 0.0007556 * (E ** 2) + 0.02736 * E + 2.9159;
    return -15 * (totalWeight - KG);
}

EFTForge.calc = { calcArmStamina, calcEED };
