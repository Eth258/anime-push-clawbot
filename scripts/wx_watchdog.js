#!/usr/bin/env node
// 微信通道看门狗：
//   1) 入站消息落库但长时间无回复 → 先探测会话；会话已失效(errcode)则重启无用，只记录
//   2) 会话正常但分发卡死 → 重启网关（15 分钟冷却）
const { DatabaseSync } = require('node:sqlite');
const { execSync } = require('node:child_process');
const fs = require('node:fs');

const DIR = '/root/.openclaw/openclaw-weixin/accounts';
const DB = '/root/.openclaw/openclaw-weixin/ref-messages.sqlite';
const STATE = '/root/.wx_watchdog.state';
const LOG = '/var/log/wx_watchdog.log';
const STALL_MS = 5 * 60 * 1000;
const COOLDOWN_MS = 15 * 60 * 1000;

function log(msg) {
  fs.appendFileSync(LOG, `${new Date().toISOString()} ${msg}\n`);
  console.log(msg);
}

function pickAccount() {
  let files = [];
  try {
    files = fs.readdirSync(DIR).filter(f => f.endsWith('.json') && !f.includes('context') && !f.includes('sync'));
  } catch { return null; }
  if (!files.length) return null;
  files.sort((a, b) => fs.statSync(`${DIR}/${b}`).mtimeMs - fs.statSync(`${DIR}/${a}`).mtimeMs);
  const name = files[0];
  try {
    const acc = JSON.parse(fs.readFileSync(`${DIR}/${name}`, 'utf8'));
    let ctx = '';
    try { ctx = (JSON.parse(fs.readFileSync(`${DIR}/${name.replace('.json', '.context-tokens.json')}`, 'utf8')) || {})[acc.userId] || ''; } catch {}
    return { ...acc, ctx };
  } catch { return null; }
}

async function sessionAlive() {
  const acc = pickAccount();
  if (!acc) return true;
  try {
    const r = await fetch(acc.baseUrl.replace(/\/$/, '') + '/ilink/bot/getconfig', {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + acc.token,
        'AuthorizationType': 'ilink_bot_token',
        'iLink-App-Id': 'bot',
        'iLink-App-ClientVersion': String((2 << 16) | (4 << 8) | 10),
        'X-WECHAT-UIN': Buffer.from(String(Math.floor(Math.random() * 4294967295))).toString('base64'),
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ ilink_user_id: acc.userId, context_token: acc.ctx,
                             base_info: { channel_version: '2.4.10', bot_agent: 'openclaw' } }),
      signal: AbortSignal.timeout(15000),
    });
    const j = await r.json();
    if (j && j.errcode) {
      log(`会话失效 errcode=${j.errcode} ${j.errmsg || ''}，重启无效，跳过`);
      return false;
    }
    return true;
  } catch (e) {
    log('会话探测异常: ' + e.message + '（按可用处理）');
    return true;
  }
}

async function main() {
  let lastRestart = 0;
  try { lastRestart = parseInt(fs.readFileSync(STATE, 'utf8').trim(), 10) || 0; } catch {}

  let rows;
  try {
    const db = new DatabaseSync(DB, { readOnly: true });
    rows = db.prepare('select direction, created_at from quote_messages where created_at > ? order by created_at')
             .all(Date.now() - 2 * 3600 * 1000);
  } catch (e) {
    log('读取数据库失败: ' + e.message);
    return;
  }

  const inbound = rows.filter(r => r.direction === 'inbound');
  if (!inbound.length) return;

  const lastIn = inbound[inbound.length - 1].created_at;
  const replied = rows.some(r => r.direction === 'outbound' && r.created_at > lastIn);
  const age = Date.now() - lastIn;
  if (replied || age <= STALL_MS) return;

  if (Date.now() - lastRestart < COOLDOWN_MS) {
    log(`卡死中，冷却期内（距上次重启 ${Math.round((Date.now() - lastRestart) / 60000)} 分钟）`);
    return;
  }

  if (!(await sessionAlive())) return;

  log(`分发卡死：最后入站 ${new Date(lastIn).toISOString()}，已 ${Math.round(age / 60000)} 分钟无回复，重启网关`);
  try {
    execSync('systemctl restart openclaw-gateway', { timeout: 60000 });
    fs.writeFileSync(STATE, String(Date.now()));
    log('网关已重启');
  } catch (e) {
    log('重启失败: ' + e.message);
  }
}

main().catch(e => log('看门狗异常: ' + e.message));
