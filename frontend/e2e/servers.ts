export const frontendPort = Number(process.env.WM_BROWSER_UI_PORT || '18765')
export const backendPort = Number(process.env.WM_BROWSER_API_PORT || '18766')
export const frontendOrigin = `http://127.0.0.1:${frontendPort}`
export const backendOrigin = `http://127.0.0.1:${backendPort}`
