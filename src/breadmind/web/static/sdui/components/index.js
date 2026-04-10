// src/breadmind/web/static/sdui/components/index.js
import layout from './layout.js';
import display from './display.js';
import data from './data.js';
import interactive from './interactive.js';

const registry = {
  ...layout,
  ...display,
  ...data,
  ...interactive,
};

export default registry;
