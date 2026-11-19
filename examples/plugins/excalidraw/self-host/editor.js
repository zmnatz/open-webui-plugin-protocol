// The one module the editor page imports when it is self-hosted: React, ReactDOM and Excalidraw
// (see ../templates/viewer.html). build.sh bundles it into dist/editor.js.
import * as React from "react";
import { createRoot } from "react-dom/client";
import { Excalidraw, MainMenu, convertToExcalidrawElements } from "@excalidraw/excalidraw";

export { React, createRoot, Excalidraw, MainMenu, convertToExcalidrawElements };
