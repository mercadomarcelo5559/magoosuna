// Negocios reales encontrados en búsquedas web (directorios y sitios de cada clínica), en el mismo formato
// que devuelve Google Places API (places:searchText). Se usa porque esta ejecución no tuvo API key de Google.
// Lote del 2026-11-19: Lomas (San Luis Potosí), Centro (Aguascalientes) y Altozano/Centro (Morelia).
// Una respuesta por zona, igual que "Arma las búsquedas" -> "Busca en Google Maps".
// Calificaciones: de agregadores (no de Google). Reseñas: no se obtuvieron textos, se dejan vacías (no se inventan).
const DIAS = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'];
// h: { 1: [9, 19], ..., 6: [10, 14] }  (0 = domingo)
const hm = (x) => ({ hour: Math.floor(x), minute: Math.round((x % 1) * 60) });
const txt = (x) => `${Math.floor(x)}:${String(Math.round((x % 1) * 60)).padStart(2, '0')}`;
const rangos = (v) => (Array.isArray(v[0]) ? v : [v]);
const horario = (h) => {
  if (!h) return undefined;
  const periods = Object.entries(h).flatMap(([d, v]) => rangos(v).map(([a, c]) => ({ open: { day: +d, ...hm(a) }, close: { day: +d, ...hm(c) } })));
  const orden = [1, 2, 3, 4, 5, 6, 0];
  const weekdayDescriptions = orden.map((d) => `${DIAS[d]}: ${h[d] ? rangos(h[d]).map(([a, c]) => `${txt(a)}–${txt(c)}`).join(', ') : 'Cerrado'}`);
  return { periods, weekdayDescriptions };
};
const semana = (a, c, sab, dom) => {
  const h = { 1: [a, c], 2: [a, c], 3: [a, c], 4: [a, c], 5: [a, c] };
  if (sab) h[6] = sab;
  if (dom) h[0] = dom;
  return h;
};
const maps = (n, d) => `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${n}, ${d}`)}`;
const lugar = (id, nombre, direccion, tel, web, extra = {}) => ({
  id: `web-${id}`,
  displayName: { text: nombre },
  formattedAddress: direccion,
  internationalPhoneNumber: tel || undefined,
  websiteUri: web || undefined,
  googleMapsUri: maps(nombre, direccion),
  rating: extra.rating,
  userRatingCount: extra.total,
  regularOpeningHours: horario(extra.h),
  reviews: [],
  businessStatus: 'OPERATIONAL',
});

const LV = (r) => ({ 1: r, 2: r, 3: r, 4: r, 5: r });
module.exports = [
  {
    textQuery: 'dentista en Lomas, San Luis Potosí, San Luis Potosí',
    places: [
      lugar('centro-dental-lomas-slp', 'Centro Dental Lomas', 'Cordillera de los Himalaya 106, Lomas 3ra Secc., San Luis Potosí, S.L.P.', '+52 444 813 6473', 'https://www.centrodentallomas.com/', { h: { ...LV([[11, 14], [16, 20]]), 6: [10, 15], 0: [10, 15] } }),
      lugar('dra-caribel-andrade', 'Dra. Caribel Andrade', 'Montes Blancos 180, int. 13, Lomas 2da Secc., San Luis Potosí, S.L.P.', '+52 444 828 3251', ''),
      lugar('perfect-smile-slp', 'The Perfect Smile Dental Laser Clinic', 'Av. Cordillera de los Himalaya 611-5, Lomas 4ta Secc., San Luis Potosí, S.L.P.', '+52 444 825 2253', '', { h: { 1: [10, 20.5], 2: [10, 20.5], 3: [10, 20.5], 4: [10, 20.5], 5: [10, 20], 6: [10, 14.5] } }),
      lugar('odontologia-estetica-integral-slp', 'Odontología Estética e Integral', 'Cordillera de los Himalaya 130, Lomas 3ra Secc., San Luis Potosí, S.L.P.', '+52 444 859 4733', ''),
      lugar('silva-herzog', 'Clínica Odontológica Silva-Herzog', 'Cofre de Perote 249, Lomas, San Luis Potosí, S.L.P.', '+52 444 825 2158', ''),
    ],
  },
  {
    textQuery: 'dentista en Centro, Aguascalientes, Aguascalientes',
    places: [
      lugar('dental-dr-alex', 'Clínica Dental Dr. Alex', 'Gral. Miguel Barragán 433, local 3, Zona Centro, 20000 Aguascalientes, Ags.', '+52 449 979 4402', ''),
      lugar('especialidades-dentales-ags', 'Centro de Especialidades Dentales de Aguascalientes', 'Francisco Primo Verdad 241, Zona Centro, 20000 Aguascalientes, Ags.', '+52 449 915 1781', ''),
      lugar('denut', 'Denut Clínica Dental', 'San Cayetano 239, San Cayetano, 20010 Aguascalientes, Ags.', '+52 449 186 4546', 'https://denut.ueniweb.com/'),
      lugar('dental-corporativa-ags', 'Dental Corporativa', 'Fresnillo 210, Col. Primavera, 20050 Aguascalientes, Ags.', '+52 449 915 1559', ''),
    ],
  },
  {
    textQuery: 'dentista en Altozano, Morelia, Michoacán',
    places: [
      lugar('dra-marijose-mayes', 'Dra. Marijose Mayes Merelles', 'Hospital Ángeles Altozano, consultorio 413 A, piso 4, Morelia, Mich.', '+52 443 530 0920', 'https://www.doctoralia.com.mx/perfil/marijose-mayes-merelles'),
      lugar('agata-estetica-dental', 'Ágata Estética Dental', 'Torre B, piso 3, consultorio 306B, Altozano, Morelia, Mich.', '+52 443 330 7681', 'https://agataesteticadental.mx/agata/morelia'),
      lugar('cenit-morelia', 'CÉNIT Odontología Avanzada', 'Ana María Gallaga 911, int. 102/105, Torre Médica Centro, Morelia, Mich.', '+52 443 703 0405', ''),
      lugar('dental-white-morelia', 'Dental White', 'Virrey de Mendoza 435, Centro, Morelia, Mich.', '+52 443 360 5858', 'https://dental-white-1.ueniweb.com/'),
      lugar('san-dental-morelia', 'San Dental', 'Revolución 359, Morelia, Mich.', '+52 443 236 0615', ''),
    ],
  },
];
