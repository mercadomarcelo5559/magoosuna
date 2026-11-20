// Negocios reales encontrados en búsquedas web (directorios y sitios de cada clínica), en el mismo formato
// que devuelve Google Places API (places:searchText). Se usa porque esta ejecución no tuvo API key de Google.
// Lote del 2026-11-20: Distrito Uno (Chihuahua), Centro (Hermosillo) y Tres Ríos (Culiacán).
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
    textQuery: 'dentista en Distrito Uno, Chihuahua, Chihuahua',
    places: [
      lugar('distrito-dental', 'Distrito Dental', 'Vía Lombardía 5901, int. 105, Distrito I, Chihuahua, Chih.', '+52 614 441 8136', 'https://www.distritodental.com/', { h: { ...LV([9, 19]), 6: [9, 14] } }),
      lugar('grupo-dental-cumbre', 'Grupo Dental Cumbre', 'Vía Lombardía 5705, suite 302, Distrito 1, Col. Saucito, Chihuahua, Chih.', '+52 614 414 7808', 'https://www.grupodentalcumbre.com/'),
      lugar('dentalite', 'Dentalite', 'Periférico de la Juventud 6900, Chihuahua, Chih.', '+52 614 413 4732', 'https://www.dentalite.mx/', { h: { ...LV([9, 19]), 6: [10, 14] } }),
      lugar('dentalia-fashion-mall-chih', 'dentalia Chihuahua Fashion Mall', 'Periférico de la Juventud 3501, Plaza del Sol, Chihuahua, Chih.', '+52 614 430 3127', 'https://www.dentalia.com/dentistas/chihuahua'),
    ],
  },
  {
    textQuery: 'dentista en Centro, Hermosillo, Sonora',
    places: [
      lugar('centro-dental-integral-hmo', 'Centro Dental Integral', 'Revolución 203 esq. Veracruz, local 6A, Centro, Hermosillo, Son.', '+52 662 210 2667', 'https://www.dentistaenhermosillo.com/', { h: { ...LV([9, 19]), 6: [9, 16] } }),
      lugar('centro-dental-sonora', 'Centro Dental Sonora', 'Blvd. Morelos 138, Hermosillo, Son.', '+52 662 210 3187', 'https://www.centrodentalsonora.com.mx/', { h: { ...LV([8, 20]), 6: [8, 15] } }),
      lugar('clinica-dental-juarez-hmo', 'Clínica Dental Juárez', 'Av. Constituyentes 113, Misión del Real, Hermosillo, Son.', '', 'https://www.clinicadentaljuarezmx.com/', { h: { ...LV([[10, 13.5], [16, 19.5]]), 6: [10, 15] } }),
      lugar('espinoza-clinica-dental', 'Espinoza Clínica Dental', 'Blvd. Las Torres 604, Bella Vista, Hermosillo, Son.', '+52 662 256 4085', 'https://www.espinozaclinicadental.com/index.html'),
      lugar('arcada-hmo', 'ARCADA Clínica Dental', 'Blvd. Luis Donaldo Colosio 248, Hermosillo, Son.', '+52 662 213 0857', 'https://arcadaclinicadental.com/', { h: { ...LV([8, 20]), 6: [8, 20] } }),
    ],
  },
  {
    textQuery: 'dentista en Tres Ríos, Culiacán, Sinaloa',
    places: [
      lugar('odontologicas-del-rio', 'Centro de Especialidades Odontológicas del Río', 'Diego Valadez 164 Pte., 2do piso, local 203, Desarrollo Urbano Tres Ríos, Culiacán, Sin.', '+52 667 752 1548', ''),
      lugar('nutri-odent', 'Nutri Odent', 'Blvd. Alfonso G. Calderón 2595, Country Tres Ríos, Culiacán, Sin.', '+52 667 775 3939', ''),
      lugar('ortodoncia-tres-rios', 'Consultorio de Ortodoncia Tres Ríos', 'Av. Milenium, Ampliación Desarrollo Urbano Tres Ríos, Culiacán, Sin.', '+52 667 758 7900', ''),
      lugar('cassabi', 'Cassabi Clínica Dental', 'Culiacán, Sin.', '+52 667 584 2156', ''),
      lugar('dental-americas', 'Dental Americas', 'Culiacán, Sin.', '+52 667 320 1086', 'https://dentalamericas.mx/'),
      lugar('ingenieria-dental', 'Ingeniería Dental', 'Culiacán, Sin.', '+52 667 117 4169', 'http://ingenieriadental.mx/'),
    ],
  },
];
