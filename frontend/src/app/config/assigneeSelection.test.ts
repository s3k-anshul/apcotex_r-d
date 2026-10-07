/**
 * Run: node --experimental-strip-types src/app/config/assigneeSelection.test.ts
 */
import assert from "node:assert/strict";
import { addAssigneeNames, removeAssigneeName } from "./assigneeSelection.ts";

const many = addAssigneeNames([], "LG Chem, Synthomer, Company C");
assert.deepEqual(many, ["LG Chem", "Synthomer", "Company C"]);

const withDuplicate = addAssigneeNames(["LG Chem"], "lg chem, Synthomer");
assert.deepEqual(withDuplicate, ["LG Chem", "Synthomer"]);

const manual = addAssigneeNames(["Synthomer"], "Private Lab Name");
assert.deepEqual(manual, ["Synthomer", "Private Lab Name"]);

assert.deepEqual(removeAssigneeName(many, "Synthomer"), ["LG Chem", "Company C"]);

console.log("assigneeSelection checks passed");
