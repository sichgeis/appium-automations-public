// Lokale Kurzdiagnose: niemals rohe Geräte-Logs speichern oder ausgeben.
const fs = require('node:fs');
const path = require('node:path');
const {startSyslogService} = require('../node_modules/appium-xcuitest-driver/node_modules/appium-ios-device/build/lib/services.js');
const config = JSON.parse(fs.readFileSync(path.join(__dirname, '../config.local.json'), 'utf8'));
const counts = {};
const duration = Number(process.argv[2] || 300);
if (!Number.isInteger(duration) || duration < 10 || duration > 300) process.exit(2);
const rules = [
  ['apple_profile_rejected', /REJECT_PROFILE|permanently rejected profile/i],
  ['authorization_denied', /authorized["\s:]+false|No online authorization/i],
  ['authorization_allowed', /authorized["\s:]+true/i],
  ['network_timeout', /timed?\s*out|NSURLError.*-1001|error.*-1001/i],
  ['network_offline', /NSURLError.*-1009|not connected to the internet/i],
  ['dns_failure', /NSURLError.*-1003|cannot find host|could not resolve/i],
  ['tls_failure', /NSURLError.*-120[0-6]|SSL.*error|TLS.*fail|certificate.*expired/i],
  ['http_service_failure', /HTTP[^\n]{0,30}\b50[234]\b/i],
  ['app_unverified', /not (?:been )?explicitly trusted|certificate is not trusted|not verified/i],
];
let service;
const finish = () => {
  if (service) service.close();
  process.stdout.write('RB_DIAG ' + JSON.stringify({event: 'finished', counts}) + '\n');
  process.exit(0);
};
const watchdog = setTimeout(() => {
  process.stdout.write('RB_DIAG {"event":"service_timeout"}\n');
  finish();
}, 65000);
process.on('SIGTERM', finish);
process.on('SIGINT', finish);
(async () => {
  try {
    service = await startSyslogService(config.udid);
    service.start((line) => {
      // Nur Verifikations-/Signierungsdienste; keine Händler- oder UI-Inhalte.
      if (!/\b(?:amfid|misagent|online-auth-agent|trustd|installd|profiled)\b/i.test(line)) return;
      // Nur direkt zuordenbare Online-Autorisierung, nicht allgemeine trustd-Ereignisse.
      if (!/ppq\.apple\.com|online.auth|WebDriverAgent|REJECT_PROFILE/i.test(line)
          && !line.includes(config.wda_bundle_id)) return;
      for (const [category, pattern] of rules) {
        if (pattern.test(line)) {
          counts[category] = (counts[category] || 0) + 1;
          if (counts[category] === 1) process.stdout.write('RB_DIAG ' + JSON.stringify({category}) + '\n');
        }
      }
    });
    process.stdout.write('RB_DIAG ' + JSON.stringify({event:'ready',duration_seconds:duration}) + '\n');
    clearTimeout(watchdog);
    setTimeout(finish, duration * 1000);
  } catch {
    process.stdout.write('RB_DIAG {"event":"service_unavailable"}\n');
    finish();
  }
})();
