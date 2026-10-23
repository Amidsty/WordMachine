import { createApp } from 'vue'
import App from './app/App.vue'
import { createServices, servicesKey } from './app/services'
import { createAppRouter } from './app/router'
import './shared/styles/theme.css'

const services = createServices()
const router = createAppRouter(services)
const app = createApp(App)
app.provide(servicesKey, services)
app.use(router)
void router.isReady().then(() => app.mount('#app'))
