// Negocios reales encontrados en búsquedas web (directorios y sitios de cada clínica), en el mismo formato
// que devuelve Google Places API (places:searchText). Se usa porque esta ejecución no tuvo API key de Google.
// Lote del 2026-11-10: San Pedro Garza García, Cumbres y Centro (Monterrey, NL).
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
    textQuery: 'dentista en San Pedro Garza García, Nuevo León',
    places: [
      lugar('dentjoy', 'Clínica Dental Dentjoy', 'Calz. del Valle 355, local 2-2, Del Valle, 66220 San Pedro Garza García, N.L.', '+52 81 1620 5131', '', { h: { ...LV([15, 20]), 6: [9, 15] } }),
      lugar('orthostetics', 'Orthostetics Dental Clinic', 'Plaza Punto Lomas, Lomas del Valle 430, piso 3, local 6, 66256 San Pedro Garza García, N.L.', '+52 81 8335 5867', '', { h: { ...LV([10, 19]), 6: [9, 14] } }),
      lugar('health-wellness-dental', 'Health and Wellness Dental Center', 'Río Manzanares 415, Del Valle, 66220 San Pedro Garza García, N.L.', '+52 81 8335 9747', '', { h: { ...LV([10, 18.5]), 6: [8, 13.5] } }),
      lugar('mc-dentistas', 'M&C Dentistas', 'Río Missouri 500, Valle de Santa Engracia, 66268 San Pedro Garza García, N.L.', '+52 81 2230 5463', '', { h: { ...LV([10, 20]), 6: [10, 19] } }),
      lugar('dentalmx-san-pedro', 'Dental.mx San Pedro', 'Río Colorado 226, local 1, Del Valle, 66220 San Pedro Garza García, N.L.', '+52 81 1912 0519', ''),
      lugar('dental-klinik', 'Dental Klinik Especialistas', 'Plaza Punto Lomas, Lomas del Valle 430, 66256 San Pedro Garza García, N.L.', '+52 81 8335 4184', '', { h: { ...LV([10, 19]), 6: [10, 14] } }),
      lugar('dental-reyna', 'Clínica Dental Reyna', 'Privada Benito Juárez 124, Lomas de Tampiquito, 66240 San Pedro Garza García, N.L.', '+52 81 8087 9415', ''),
    ],
  },
  {
    textQuery: 'dentista en Cumbres, Monterrey, Nuevo León',
    places: [
      lugar('dental-smile-cumbres', 'Clínica Dental Smile', 'Paseo de los Leones 1613-1, Cumbres, Monterrey, N.L.', '+52 81 1365 1610', 'https://dental-smile.mx/', { h: { ...LV([[10, 14], [15, 19]]), 6: [10, 14] } }),
      lugar('odontologia-cumbres', 'Odontología Cumbres', 'Paseo de los Leones 1388, L-6 altos, Cumbres 1er Sector, 64610 Monterrey, N.L.', '+52 81 8347 0246', 'https://odontologiacumbres.com/nosotros'),
      lugar('ciel-cumbres', 'Ciel Dentistas Cumbres', 'Alejandro de Rodas 3102, local 21, 64610 Monterrey, N.L.', '+52 81 8310 0800', ''),
      lugar('centro-odontologico-familiar', 'Centro Odontológico Familiar', '15va Avenida 474, Cumbres 2º Sector, 64610 Monterrey, N.L.', '+52 81 8881 8990', ''),
      lugar('centro-dental-cumbres', 'Centro Dental Cumbres', 'Alejandro de Rodas 4401-B, Pedregal de las Cumbres, Monterrey, N.L.', '+52 81 4444 6989', '', { h: { ...LV([9, 19]), 6: [9, 15] } }),
      lugar('dental-care-kids-cumbres', 'Dental Care Kids Cumbres', 'Paseo de los Leones 105, Cumbres Elite, 64349 Monterrey, N.L.', '+52 81 2470 0352', '', { h: { ...LV([10, 20]), 6: [9, 13] } }),
      lugar('dentalia-plaza-cumbres', 'dentalia Plaza Cumbres', 'Paseo de los Leones 3399, local 1104, Bosques de las Cumbres, 64619 Monterrey, N.L.', '+52 81 1095 2138', 'https://www.dentalia.com/'),
    ],
  },
  {
    textQuery: 'dentista en Centro, Monterrey, Nuevo León',
    places: [
      lugar('regiodental-centro', 'Regiodental Centro', 'Juan Álvarez 443, Centro, 64000 Monterrey, N.L.', '+52 81 8004 0354', 'https://regiodental.com/', { h: { ...LV([10, 19]), 6: [9, 16] } }),
      lugar('clinica-dental-mexico', 'Clínica Dental México', 'C. Ruperto Martínez Ote. 617, Centro, 64000 Monterrey, N.L.', '+52 81 8343 5807', ''),
      lugar('dental-clinic-mitras', 'Dental Clinic (Mitras Centro)', 'Mitras Centro, Monterrey, N.L.', '+52 81 2886 8486', 'https://dental-clinic-12.ueniweb.com/', { h: LV([7, 18]) }),
      lugar('dentistas-teran', 'Dentistas Terán', 'Arquitectos 102, Tecnológico, Monterrey, N.L.', '+52 81 8358 4994', 'https://dentistasteran.com.mx/', { h: { ...LV([[9, 13], [15, 19]]), 6: [9, 13] } }),
    ],
  },
];
