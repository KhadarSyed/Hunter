// The amCharts 5 bundle inlined into deck.html (decks work offline: no CDN at view time).
// Rebuild after changing the pinned version (5.21.2, amcharts5-geodata 5.1.6), from a folder where both are installed:
//   esbuild amcharts_entry.js --bundle --minify --format=iife --outfile=amcharts5.bundle.js
//   esbuild amcharts_geodata_entry.js --bundle --minify --format=iife --outfile=amcharts5.usa.js
import * as am5 from "@amcharts/amcharts5";
import * as am5xy from "@amcharts/amcharts5/xy";
import * as am5percent from "@amcharts/amcharts5/percent";
import * as am5hierarchy from "@amcharts/amcharts5/hierarchy";
import * as am5map from "@amcharts/amcharts5/map";
import * as am5flow from "@amcharts/amcharts5/flow";
import am5themes_Animated from "@amcharts/amcharts5/themes/Animated";

Object.assign(window, { am5, am5xy, am5percent, am5hierarchy, am5map, am5flow, am5themes_Animated });
