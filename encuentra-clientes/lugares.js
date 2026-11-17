// Negocios reales encontrados en búsquedas web (directorios y sitios de cada clínica), en el mismo formato
// que devuelve Google Places API (places:searchText). Se usa porque esta ejecución no tuvo API key de Google.
// Lote del 2026-11-17: Coyoacán, Narvarte y Santa Fe (CDMX).
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
    textQuery: 'dentista en Coyoacán, Ciudad de México',
    places: [
      lugar('dentalia-oasis-coyoacan', 'dentalia Oasis Coyoacán', 'Plaza Oasis Coyoacán, Av. Miguel Ángel de Quevedo / Romero de Terreros, sótano 1, Coyoacán, CDMX', '+52 55 5554 4990', 'https://www.dentalia.com/clinica/dentalia-oasis-coyoacan', { h: { ...LV([9, 20]), 6: [9, 18], 0: [9, 18] } }),
      lugar('eolodent-coyoacan', 'Clínica Dental Eolodent Coyoacán', 'Av. Miguel Ángel de Quevedo 928, Parque San Andrés, Coyoacán, CDMX', '+52 56 4893 4006', ''),
      lugar('la-clinica-dental-coyoacan', 'La Clínica Dental Coyoacán', 'Coyoacán, CDMX', '+52 55 7583 9457', 'https://dentistacoyoacan.com.mx/', { h: { ...LV([9, 20]), 6: [9, 20] } }),
      lugar('giordani-dental', 'Giordani · Dr. Jesús Alberto Aguirre', 'Calle Otomíes 212, Ajusco, Coyoacán, CDMX', '+52 55 3429 8381', 'https://giordani.lat/', { h: { ...LV([9, 20]), 6: [9, 16] } }),
      lugar('dentrica', 'Dentrica Clínica Dental Coyoacán', 'Árbol de Fuego 21, Candelaria Coyoacán, CDMX', '+52 56 1348 6587', 'https://dentrica.com.mx/'),
    ],
  },
  {
    textQuery: 'dentista en Narvarte, Ciudad de México',
    places: [
      lugar('la-clinica-dental-narvarte', 'La Clínica Dental Narvarte', 'Xola 1312, Narvarte Poniente, Benito Juárez, 03020 CDMX', '+52 55 8854 7358', 'https://laclinica.mx/', { h: { ...LV([9, 20]), 6: [8, 16] } }),
      lugar('odontologia-integral-gc', 'Odontología Integral GC', 'Casas Grandes 74, Narvarte Oriente, Benito Juárez, CDMX', '+52 55 1239 1476', 'https://odontologiaintegralgc.com/', { h: { ...LV([9, 19]), 6: [10, 15] } }),
      lugar('wedental', 'WeDental', 'Heriberto Frías 847, Narvarte Poniente, Benito Juárez, CDMX', '+52 55 7938 3662', 'https://www.wedental.mx/contacto/', { h: { ...LV([9, 21]), 6: [9, 18] } }),
      lugar('denxal-narvarte', 'Denxal Clínica Dental Narvarte', 'La Quemada 50, Narvarte Oriente, Benito Juárez, CDMX', '+52 55 2063 2729', '', { h: { ...LV([10, 20]), 6: [10, 15] } }),
    ],
  },
  {
    textQuery: 'dentista en Santa Fe, Ciudad de México',
    places: [
      lugar('la-clinica-dental-santa-fe', 'La Clínica Dental Santa Fe', 'Edificio Insitu, Torre A, Vasco de Quiroga 4001, piso 8 D1, Santa Fe, 05348 CDMX', '+52 55 8854 8352', 'https://laclinicadentalsantafe.com/contactanos/', { h: { ...LV([9, 20]), 6: [9, 20] } }),
      lugar('dentology-santa-fe', 'Dentology Santa Fe', 'Santa Fe 498, Contadero, Cuajimalpa, 05348 CDMX', '+52 55 5110 9500', 'https://www.dentology.com.mx/santa-fe-cdmx', { h: { ...LV([9, 18]), 6: [9, 14] } }),
      lugar('dex-santa-fe', 'DEX! Clínica Dental Santa Fe', 'Centro Infinito, Vasco de Quiroga 4299, local 306, Santa Fe, CDMX', '+52 55 3679 3441', ''),
    ],
  },
];
