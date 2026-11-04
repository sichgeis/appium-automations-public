// Quellen: Appiums vorhandener os_trace-Parser und pymobiledevice3 OsTraceService.
// Nur lokale Verarbeitung; keine Rohlogs speichern oder ausgeben.
import fs from 'node:fs';
import {createRequire} from 'node:module';
import {spawnSync} from 'node:child_process';
import {framePlist} from '../node_modules/appium-xcuitest-driver/node_modules/appium-ios-remotexpc/build/src/lib/plist/index.js';
import {SyslogProtocolParser, parseActivityReply} from '../node_modules/appium-xcuitest-driver/node_modules/appium-ios-remotexpc/build/src/services/ios/syslog-service/syslog-entry-parser.js';
const require = createRequire(import.meta.url);
const {startLockdownSession, connectPort, connectPortSSL} = require('../node_modules/appium-xcuitest-driver/node_modules/appium-ios-device/build/lib/utilities.js');
const config = JSON.parse(fs.readFileSync(new URL('../config.local.json', import.meta.url), 'utf8'));
const counts = {};
let socket;
const emit = (value) => process.stdout.write('RB_DIAG ' + JSON.stringify(value) + '\n');
const rules = [
  ['profile_rejected', /REJECT_PROFILE|permanently rejected profile/i],
  ['online_authorization_denied', /authorized["\s:]+false|no online authorization/i],
  ['online_authorization_allowed', /authorized["\s:]+true/i],
  ['verification_tls_error', /NSURLError[^\n]{0,80}-120[0-6]|SSL[^\n]{0,30}error|TLS[^\n]{0,30}fail/i],
  ['verification_timeout', /timed?\s*out|NSURLError[^\n]{0,80}-1001/i],
  ['verification_dns_error', /NSURLError[^\n]{0,80}-1003|cannot find host|could not resolve/i],
  ['certificate_revoked', /certificate[^\n]{0,40}revoked|revoked\s*[=:]\s*1/i],
  ['certificate_expired', /certificate[^\n]{0,40}expired/i],
  ['profile_unverified', /not (?:been )?explicitly trusted|certificate is not trusted|not verified/i],
];
const parser = new SyslogProtocolParser((entry) => {
  counts.stream_entries = (counts.stream_entries || 0) + 1;
  const processName = entry.filename.split('/').pop();
  if (!['online-auth-agent', 'amfid', 'misagent', 'installd', 'trustd', 'profiled'].includes(processName)) return;
  counts.signing_daemon_entries = (counts.signing_daemon_entries || 0) + 1;
  const text = entry.message;
  const related = /ppq\.apple\.com|online.auth|WebDriverAgent|SigningProbe|REJECT_PROFILE/i.test(text)
    || [config.wda_bundle_id, config.signing_probe_bundle_id].some(v => v && text.includes(v));
  if (processName !== 'online-auth-agent' && !related) return;
  counts.signing_service_entries = (counts.signing_service_entries || 0) + 1;
  for (const [category, pattern] of rules) {
    if (pattern.test(text)) counts[category] = (counts[category] || 0) + 1;
  }
}, () => { counts.parser_errors = (counts.parser_errors || 0) + 1; });
const timer = setTimeout(() => {socket?.destroy(); emit({event:'timeout', counts}); process.exit(2);}, 25000);
try {
  const lockdown = await startLockdownSession(config.udid);
  let service;
  try { service = await lockdown.startService('com.apple.os_trace_relay'); }
  finally { lockdown.close(); }
  socket = service.EnableServiceSSL
    ? await connectPortSSL(config.udid, service.Port)
    : await connectPort(config.udid, service.Port);
  socket.pause();
  let replyBuffer = Buffer.alloc(0);
  let started = false;
  socket.on('data', (chunk) => {
    if (started) {parser.addData(chunk); return;}
    replyBuffer = Buffer.concat([replyBuffer, chunk]);
    try {
      const reply = parseActivityReply(replyBuffer);
      if (!reply) return;
      if (reply.response.Status !== 'RequestSuccessful') {
        emit({event:'native_stream_refused'}); socket.destroy(); clearTimeout(timer); return;
      }
      started = true;
      emit({event:'native_stream_ready'});
      parser.addData(reply.rest);
      replyBuffer = Buffer.alloc(0);
      if (process.argv.includes('--launch-probe') && config.signing_probe_bundle_id) {
        const launch = spawnSync('xcrun', ['devicectl', 'device', 'process', 'launch',
          '--device', config.udid, config.signing_probe_bundle_id, '--json-output', '-', '--timeout', '10'],
          {env:{...process.env, DEVELOPER_DIR:process.env.DEVELOPER_DIR || '/Applications/Xcode.app/Contents/Developer'},
            encoding:'utf8', timeout:15000});
        emit({event:'probe_launch', exit:launch.status});
      }
      setTimeout(() => {socket.destroy(); clearTimeout(timer); emit({event:'finished', counts});}, 10000);
    } catch {emit({event:'native_protocol_error'}); socket.destroy(); clearTimeout(timer);}
  });
  socket.on('error', () => {emit({event:'native_socket_error'}); clearTimeout(timer);});
  socket.write(framePlist({Request:'StartActivity', MessageFilter:65535, StreamFlags:60, Pid:-1}));
  socket.resume();
} catch {
  clearTimeout(timer); socket?.destroy(); emit({event:'native_service_unavailable'});
}
