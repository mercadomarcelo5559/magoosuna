// Negocios reales encontrados en búsquedas web (directorios y sitios de cada clínica), en el mismo formato
// que devuelve Google Places API (places:searchText). Se usa porque esta ejecución no tuvo API key de Google.
// Lote del 2026-11-09: Polanco, Roma Norte y Del Valle (CDMX).
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
    textQuery: 'dentista en Polanco, Ciudad de México',
    places: [
      lugar('moons-polanco', 'Moons Polanco', 'Lafontaine 73, piso 3, Polanco III Secc., Miguel Hidalgo, 11540 CDMX', '+52 55 4440 8128', 'https://mymoons.mx/ubicaciones/cdmx-polanco', { h: { ...LV([10, 18]), 6: [10, 18] } }),
      lugar('la-clinica-dental-polanco', 'La Clínica Dental Polanco', 'Presa Sanalona 8, Irrigación, Miguel Hidalgo, 11500 CDMX', '+52 55 8854 8351', 'https://laclinicapolanco.dental/', { h: { ...LV([9, 20]), 6: [9, 14] } }),
      lugar('dental-polanco-v', 'La Clínica Dental Polanco V', 'Petrarca 223, Polanco V Secc., Miguel Hidalgo, CDMX', '+52 55 5014 0326', 'https://dentalpolanco.dentist/', { h: { ...LV([9, 20]), 6: [9, 20] } }),
      lugar('vitadent-pro', 'Vitadent Pro', 'Calderón de la Barca 359-402, Polanco, Miguel Hidalgo, CDMX', '+52 55 5545 9190', 'https://www.vitadentpro.com/', { h: LV([9.5, 19]) }),
      lugar('dds-dental-studio', 'DDS Dental Studio', 'Torcuato Tasso 315, Polanco, Miguel Hidalgo, CDMX', '+52 55 9039 1270', 'https://www.ddsdentalstudio.com/', { h: { ...LV([10, 19]), 6: [10, 15] } }),
      lugar('clinica-dental-polanco-hegel', 'Clínica Dental Polanco (Hegel)', 'Hegel 209, Polanco V Secc., Miguel Hidalgo, CDMX', '+52 55 5255 1817', ''),
    ],
  },
  {
    textQuery: 'dentista en Roma Norte, Ciudad de México',
    places: [
      lugar('lumbra-dental-roma', 'Lumbra Dental Roma', 'Querétaro 227, Roma Norte, Cuauhtémoc, CDMX', '+52 56 1139 1093', '', { h: { ...LV([11, 20]), 6: [11, 17] } }),
      lugar('rl-orthodontics', 'RL Orthodontics', 'Durango 33, Roma Norte, Cuauhtémoc, CDMX', '+52 55 7261 3287', 'https://rlorthodontics.com/en/index.html', { h: { 1: [10, 19], 2: [11, 20], 3: [10, 19], 4: [11, 20], 5: [10, 19], 6: [10, 16] } }),
      lugar('drdiente-roma-norte', 'Clínica DrDiente Roma Norte', 'Monterrey 147, Roma Norte, Cuauhtémoc, 06700 CDMX', '+52 56 1016 7727', 'https://www.clinicadrdiente.com/dentista-roma-norte'),
      lugar('la-clinica-dental-roma', 'La Clínica Dental Roma', 'Cozumel 22, Roma Norte, Cuauhtémoc, 06700 CDMX', '+52 55 8854 5891', ''),
      lugar('edenta', 'Edenta Odontología Integral', 'Guanajuato 92, Roma Norte, Cuauhtémoc, CDMX', '+52 55 3992 3539', ''),
      lugar('salas-diaz-roman', 'Salas Díaz Roman', 'Durango 49, Roma Norte, Cuauhtémoc, 06700 CDMX', '+52 55 5207 2247', ''),
      lugar('dental-del-angel', 'Consultorio Dental Del Ángel', 'Durango 243, despacho 902, Roma Norte, 06700 CDMX', '', ''),
    ],
  },
  {
    textQuery: 'dentista en Del Valle, Ciudad de México',
    places: [
      lugar('la-clinica-del-valle', 'La Clínica Dental Del Valle', 'Av. Universidad 845, Del Valle Sur, Benito Juárez, CDMX', '+52 55 8950 9513', 'https://laclinicadelvalle.com.mx/', { h: { ...LV([9, 20]), 6: [9, 20] } }),
      lugar('oev', 'Odontología Especializada del Valle', 'Gabriel Mancera 718, E-1, Del Valle, Benito Juárez, CDMX', '+52 55 5605 4863', 'https://odontologiaespecializadadelvalle.com/', { h: { ...LV([[9, 14], [16, 20]]), 6: [9, 15] } }),
      lugar('mariscal-sucre', 'Clínica Dental Mariscal y Sucre', 'Parque Mariscal Sucre 46, piso 1, int. 11, Del Valle Centro, Benito Juárez, CDMX', '+52 56 5768 3502', 'https://clinicadentalmariscal.com/', { h: { ...LV([9, 20]), 6: [10, 17] } }),
      lugar('dentalia-city-shops', 'dentalia City Shops Del Valle', 'Plaza City Shops, Del Valle, Benito Juárez, CDMX', '+52 55 5335 0717', 'https://www.dentalia.com/clinica/dentalia-city-shops-del-valle', { h: { ...LV([9, 20]), 6: [9, 18], 0: [9, 18] } }),
    ],
  },
];
