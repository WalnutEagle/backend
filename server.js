// Ultra-light WebSocket relay
import http from 'http';
import { WebSocketServer } from 'ws';

const PORT = process.env.PORT || 8081;
const server = http.createServer();           // no HTTP endpoints
const wss = new WebSocketServer({ server });

// keep the last packet in memory for late joiners
let lastMessage = null;

wss.on('connection', ws => {
  console.log('🔌 client connected');

  // send latest data as soon as a dashboard connects
  if (lastMessage) ws.send(lastMessage, { binary: lastMessage instanceof Buffer });

  ws.on('message', msg => {
    // remember the newest packet
    lastMessage = msg;
    // broadcast to everyone else
    wss.clients.forEach(c => c !== ws && c.readyState === ws.OPEN && c.send(msg, { binary: msg instanceof Buffer }));
  });

  ws.on('close', () => console.log('❌ client disconnected'));
});

// heartbeat so pods don’t get killed by idle timeouts
setInterval(() => {
  wss.clients.forEach(c => c.ping());
}, 30_000);

server.listen(PORT, () => console.log(`🚀 WS backend on ${PORT}`));
