/* Graph Memory Explorer — entry (ES modules) */
import { log } from "./js/dom.js";
import { initCy, updateStats } from "./js/graph.js";
import { bindGraphInteractions } from "./js/interactions.js";
import { bindPanelControls, checkHealth } from "./js/panel.js";

initCy();
bindGraphInteractions();
bindPanelControls();
checkHealth();
updateStats();
log("ready — modular explorer · neighbor buffer paging");
