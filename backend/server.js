// import http from 'http';
// import express from 'express';
// import { WebSocketServer } from 'ws';
// import { S3Client, PutObjectCommand } from '@aws-sdk/client-s3';
// import { randomUUID } from 'crypto';

// const app = express();
// const server = http.createServer(app);
// const wss = new WebSocketServer({ server });

// const s3 = new S3Client({
//   endpoint: process.env.S3_ENDPOINT,
//   region: 'us-east-1',
//   credentials: {
//     accessKeyId: process.env.MINIO_ROOT_USER,
//     secretAccessKey: process.env.MINIO_ROOT_PASSWORD
//   },
//   forcePathStyle: true
// });

// wss.on('connection', ws => {
//   console.log('Client connected');
//   ws.on('message', async msg => {
//     try {
//       const data = JSON.parse(msg.toString());
//       // broadcast to all
//       wss.clients.forEach(c => {
//         if (c.readyState === ws.OPEN) c.send(JSON.stringify(data));
//       });
//       // store image if present
//       if (data.image) {
//         const buf = Buffer.from(data.image, 'base64');
//         const key = `images/${Date.now()}-${randomUUID()}.jpg`;
//         await s3.send(new PutObjectCommand({
//           Bucket: process.env.S3_BUCKET_NAME,
//           Key: key,
//           Body: buf,
//           ContentType: 'image/jpeg'
//         }));
//       }
//       // store telemetry
//       const tkey = `telemetry/${Date.now()}-${randomUUID()}.json`;
//       await s3.send(new PutObjectCommand({
//         Bucket: process.env.S3_BUCKET_NAME,
//         Key: tkey,
//         Body: JSON.stringify(data),
//         ContentType: 'application/json'
//       }));
//     } catch (e) {
//       console.error('WS msg error:', e);
//     }
//   });
//   ws.on('close', () => console.log('Client disconnected'));
// });

// const PORT = process.env.WS_PORT || 8081;
// server.listen(PORT, () => console.log(`WS server up on ${PORT}`));



import http from 'http';
import { WebSocketServer } from 'ws';

const PORT = process.env.PORT || 8081;
const server = http.createServer();
const wss = new WebSocketServer({ server });

wss.on('connection', ws => {
  console.log('Client connected');
  ws.on('message', msg => {
    // Broadcast incoming message to all other clients
    wss.clients.forEach(client => {
      if (client !== ws && client.readyState === ws.OPEN) {
        client.send(msg);
      }
    });
  });
  ws.on('close', () => console.log('Client disconnected'));
});

server.listen(PORT, () => {
  console.log(`WebSocket server listening on port ${PORT}`);
});
