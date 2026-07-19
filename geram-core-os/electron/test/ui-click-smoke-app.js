const { app, BrowserWindow } = require('electron');

const target = process.argv[2];

app.whenReady().then(async () => {
  const window = new BrowserWindow({
    show: false,
    width: 1280,
    height: 900,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  try {
    await window.loadURL(target);
    await new Promise((resolve) => setTimeout(resolve, 2200));
    const result = await window.webContents.executeJavaScript(`(async () => {
      const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
      document.getElementById('toggleAgentes').click();
      await wait(150);
      const agentsOpen = document.getElementById('dashboardAgentes').classList.contains('activo');
      const agentCount = document.getElementById('dashboardConteo').textContent;
      document.getElementById('dashboardCerrar').click();
      document.getElementById('toggleConfig').click();
      await wait(150);
      const settingsOpen = document.getElementById('configPanel').classList.contains('activo');
      const runtimeReady = document.body.classList.contains('listo');
      return { agentsOpen, agentCount, settingsOpen, runtimeReady };
    })()`);
    process.stdout.write('GERAM_UI_SMOKE=' + JSON.stringify(result) + '\n');
  } catch (error) {
    process.stderr.write('GERAM_UI_SMOKE_ERROR=' + String(error && error.message || error) + '\n');
    process.exitCode = 1;
  } finally {
    window.destroy();
    app.quit();
  }
});
