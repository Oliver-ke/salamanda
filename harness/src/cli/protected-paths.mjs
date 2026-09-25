#!/usr/bin/env node
// Prints PROTECTED_PATHS as JSON so the Python worker's tool sandbox refuses
// exactly the paths CI's pr-rules check fails on — one list, not two.
import { PROTECTED_PATHS } from '../protected.mjs';

console.log(JSON.stringify(PROTECTED_PATHS));
