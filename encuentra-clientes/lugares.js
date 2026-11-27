// Negocios reales encontrados en búsquedas web (directorios y sitios de cada clínica), en el mismo formato
// que devuelve Google Places API (places:searchText). Se usa porque esta ejecución no tuvo API key de Google.
// Lote del 2026-11-27: Tlaquepaque Centro, Tonalá Centro y Puerto Vallarta (Jalisco).
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
    textQuery: 'dentista en Tlaquepaque Centro, San Pedro Tlaquepaque, Jalisco',
    places: [
      lugar('dental-clinic-spa', 'Dental Clinic Spa', 'Juárez 283, Centro, San Pedro Tlaquepaque, Jal.', '+52 33 1525 8603', '', { h: { ...LV([16, 20]), 6: [16, 20] } }),
      lugar('dental-tlaquepaque', 'Dental Tlaquepaque', 'Miguel Hidalgo 138, Centro, San Pedro Tlaquepaque, Jal.', '+52 33 1775 0740', '', { h: { ...LV([9, 19]), 6: [9, 14] } }),
      lugar('consultorio-dental-tlaquepaque', 'Consultorio Dental Tlaquepaque', 'Progreso 210-1, Centro, San Pedro Tlaquepaque, Jal.', '+52 33 1765 6100', '', { h: { 1: [9, 19], 2: [9, 19], 3: [9, 19], 4: [9, 19], 5: [9, 16], 6: [10, 15] } }),
      lugar('clinica-dental-diaz', 'Clínica Dental Díaz', 'Tonalá 99, Centro, San Pedro Tlaquepaque, Jal.', '+52 33 1762 4250', 'https://www.dentaldiaz.com/'),
    ],
  },
  {
    textQuery: 'dentista en Tonalá Centro, Tonalá, Jalisco',
    places: [
      lugar('consultorio-dental-tonala', 'Consultorio Dental Tonalá', 'Av. de los Maestros 180, Tonalá Centro, 45400 Tonalá, Jal.', '+52 33 3683 4680', ''),
      lugar('belladenti-tonala', 'Clínica Dental Belladenti Tonalá', 'Francisco I. Madero 93, Tonalá Centro, Tonalá, Jal.', '+52 33 3792 6525', '', { h: { ...LV([10, 19]), 6: [10, 19] } }),
      lugar('dra-andrea-carrillo', 'Dra. Andrea Carrillo', 'Emiliano Zapata 332-B, Tonalá Centro, Tonalá, Jal.', '+52 33 3724 4652', '', { h: { ...LV([16, 19]), 6: [11, 14] } }),
      lugar('dental-rm-tonala', 'Dental R.M.', 'C. Zaragoza 27-B, Tonalá Centro, Tonalá, Jal.', '+52 33 1585 7213', '', { h: { ...LV([11, 18]), 6: [11, 14] } }),
      lugar('dra-iliana-marcela', 'Consultorio Dental Dra. Iliana Marcela', 'Javier Mina 253-E, Tonalá Centro, Tonalá, Jal.', '+52 33 1300 2582', ''),
      lugar('perez-sandoval-tonala', 'Consultorio Dental Pérez Sandoval', 'P.º Loma Norte 7734-C, Loma Dorada, Tonalá, Jal.', '+52 33 3477 2006', '', { h: { ...LV([10, 20]), 6: [10, 13] } }),
    ],
  },
  {
    textQuery: 'dentista en Puerto Vallarta Centro, Puerto Vallarta, Jalisco',
    places: [
      lugar('bienstar-dental', 'Bienstar Dental', 'Hidalgo 185, local 2, Centro Pitillal, Puerto Vallarta, Jal.', '+52 322 293 7480', 'https://bienstardental.com/', { h: { ...LV([10, 19]), 6: [10, 15] } }),
      lugar('clinica-dental-vallarta-mx', 'Clínica Dental Vallarta Mx', 'Paseo Benemérito de las Américas 130, Valentín Gómez Farías, Puerto Vallarta, Jal.', '+52 322 239 8184', '', { h: { ...LV([9.5, 20]), 6: [9.5, 13.5] } }),
      lugar('dental-aleman', 'Clínica Dental Alemán', 'Popa 12, Marina Vallarta, 48335 Puerto Vallarta, Jal.', '+52 322 178 7341', 'https://www.dentalaleman.com/es/', { h: { ...LV([9, 20]), 6: [9, 15] } }),
      lugar('sevilla-dental', 'Sevilla Dental', 'Lucerna 148, Versalles, Puerto Vallarta, Jal.', '+52 322 274 3096', '', { h: LV([9, 20]) }),
      lugar('boca-oficina-dental', 'Boca Oficina Dental', 'Plaza Neptuno, local B3, Marina Vallarta, Puerto Vallarta, Jal.', '+52 322 114 4452', 'https://www.bocaoficinadental.com/en/'),
      lugar('dental-center-pv', 'Dental Center Centro de Especialidades Dentales', 'Av. Los Tules 158-6, Puerto Vallarta, Jal.', '+52 322 224 5585', '', { h: { ...LV([10, 20]), 6: [10, 14] } }),
      lugar('dental-plaza-marina', 'Clínica Dental Plaza Marina', 'Plaza Marina, local G26, Marina Vallarta, Puerto Vallarta, Jal.', '+52 322 221 0165', ''),
    ],
  },
];
