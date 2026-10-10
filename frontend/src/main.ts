import { createPinia } from "pinia";
import { createApp } from "vue";

import App from "./App.vue";
import router from "./router";
import { applyInitialTheme } from "./stores/theme";
import "./styles/main.css";

applyInitialTheme();

createApp(App).use(createPinia()).use(router).mount("#app");
