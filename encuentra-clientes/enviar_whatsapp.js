#!/usr/bin/env node
// Envía automáticamente los mensajes del día por la API oficial de WhatsApp (Meta Cloud API),
// desde el número de Pagoya, usando la plantilla aprobada por Meta.
//
// Configuración (whatsapp.json, sin secretos):
//   { "phoneNumberId": "...", "plantilla": "primer_contacto_demo", "idioma": "es_MX", "version": "v21.0", "maxPorDia": 50 }
// Token: guardado como credencial del entorno para graph.facebook.com (el proxy lo pone en cada petición)
//        o, en tu computadora, en la variable WHATSAPP_TOKEN.
//
// Plantilla (Meta solo permite que un negocio escriba primero con una plantilla aprobada):
//   Hola, equipo de {{1}}. {{2}}
//   Les preparé una recepcionista con IA de prueba, con su nombre y su horario, para que la prueben como si fueran un paciente: {{3}}
//   ¿Me dicen qué les parece?
//   Marcelo · Pagoya
//   {{1}} = nombre del consultorio, {{2}} = la observación del mensaje del día, {{3}} = link de su demo
//
// Uso: node enviar_whatsapp.js            -> envía los de prospectos.json que no se hayan enviado antes
//      node enviar_whatsapp.js --prueba   -> muestra lo que enviaría, sin enviar nada
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const D = __dirname;
const lee = (f, def) => (fs.existsSync(path.join(D, f)) ? JSON.parse(fs.readFileSync(path.join(D, f), 'utf8')) : def);
const prueba = process.argv.includes('--prueba');

const cfg = lee('whatsapp.json', null);
if (!cfg || !cfg.phoneNumberId) {
  console.log('Falta whatsapp.json con el phoneNumberId de Pagoya. No se envió nada.');
  if (!prueba) process.exit(0);
}
const filas = lee('prospectos.json', []);
const enviados = lee('enviados.json', []);
const yaEnviado = new Set(enviados.map((e) => e.numero));
const max = Number(cfg?.maxPorDia) || 50;

// "Hola, equipo de X. <observación>\n..." -> la observación es el resto de la primera línea
const observacion = (m, nombre) => {
  const linea = String(m).split('\n')[0];
  const quita = `Hola, equipo de ${nombre}.`;
  return (linea.startsWith(quita) ? linea.slice(quita.length) : linea.replace(/^Hola,[^.]*\.\s*/, '')).trim();
};
// WhatsApp no acepta saltos de línea, tabulaciones ni 4+ espacios seguidos dentro de una variable
const variable = (s) => String(s ?? '').replace(/[\n\t]+/g, ' ').replace(/ {4,}/g, '   ').trim().slice(0, 900);

const lote = [];
for (const f of filas) {
  const link = f['Abrir en WhatsApp'] || '';
  const numero = (link.match(/wa\.me\/(\d+)/) || [])[1];
  if (!numero) continue; // sin WhatsApp o sin teléfono
  if (yaEnviado.has(numero)) continue;
  if (!/^https?:\/\//.test(f.Demo || '')) { console.log(`Sin link de demo para ${f['Clínica']}: falta N8N_URL. No se envía.`); continue; }
  lote.push({ id: f.ID, clinica: f['Clínica'], numero, obs: observacion(f.Mensaje, f['Clínica']), demo: f.Demo });
  if (lote.length >= max) break;
}

const url = `https://graph.facebook.com/${cfg?.version || 'v21.0'}/${cfg?.phoneNumberId}/messages`;
const token = process.env.WHATSAPP_TOKEN || 'credencial-del-entorno'; // el proxy la reemplaza por la guardada
let ok = 0;
for (const p of lote) {
  const cuerpo = {
    messaging_product: 'whatsapp',
    to: p.numero,
    type: 'template',
    template: {
      name: cfg?.plantilla || 'primer_contacto_demo',
      language: { code: cfg?.idioma || 'es_MX' },
      components: [{ type: 'body', parameters: [variable(p.clinica), variable(p.obs), variable(p.demo)].map((text) => ({ type: 'text', text })) }],
    },
  };
  if (prueba) { console.log(`[prueba] ${p.numero} · ${p.clinica}\n  {{2}} ${p.obs}\n  {{3}} ${p.demo}`); continue; }
  try {
    const r = JSON.parse(execFileSync('curl', ['-sS', '-X', 'POST', url, '-H', `Authorization: Bearer ${token}`, '-H', 'Content-Type: application/json', '-d', JSON.stringify(cuerpo)], { encoding: 'utf8' }));
    if (r.messages?.[0]?.id) {
      ok++;
      enviados.push({ fecha: new Date().toISOString(), id: p.id, clinica: p.clinica, numero: p.numero, wamid: r.messages[0].id });
      fs.writeFileSync(path.join(D, 'enviados.json'), JSON.stringify(enviados, null, 2));
      console.log(`Enviado: ${p.clinica} (${p.numero})`);
    } else {
      console.log(`No se envió a ${p.clinica}: ${JSON.stringify(r.error || r).slice(0, 300)}`);
      if ([190, 131031, 131048, 368].includes(r.error?.code)) { console.log('Meta bloqueó o limitó la cuenta: se detiene el envío de hoy.'); break; }
    }
  } catch (e) {
    console.log(`Error con ${p.clinica}: ${String(e.message).slice(0, 200)}`);
  }
  execFileSync('sleep', ['3']); // espacio entre mensajes
}
console.log(prueba ? `Prueba: ${lote.length} mensajes listos para enviar.` : `Enviados hoy: ${ok} de ${lote.length}.`);
