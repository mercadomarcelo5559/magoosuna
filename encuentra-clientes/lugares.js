// Negocios reales encontrados en búsquedas web (directorios y sitios de cada clínica), en el mismo formato
// que devuelve Google Places API (places:searchText). Se usa porque esta ejecución no tuvo API key de Google.
// Lote del 2026-11-25: Condesa, Lindavista y Tlalpan (CDMX).
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
    textQuery: 'dentista en Condesa, Ciudad de México',
    places: [
      lugar('endodoncia-condesa', 'Endodoncia Condesa · Dra. Elvira Gil Martínez', 'Chilpancingo 71, consultorio 603, Hipódromo Condesa, CDMX', '+52 55 1645 6505', 'https://www.endodonciacondesa.com.mx/', { h: { ...LV([9, 18]), 6: [8, 12.5] } }),
      lugar('arrfox', 'ArrFox Clínica Dental', 'Atlixco 18-1, Condesa, 06140 CDMX', '+52 55 5256 4039', 'https://www.arrfox.com.mx/', { h: { ...LV([10, 20]), 6: [10, 14] } }),
      lugar('or-dental', 'OR Clínica Dental', 'Av. Mazatlán 131-B, Condesa, 06140 CDMX', '+52 55 5553 8279', 'https://www.ordental.com.mx/en'),
      lugar('om-dental', 'Om Dental', 'Tuxpan 2, Roma Sur, CDMX', '+52 55 3901 9028', 'https://omdental.mx/en'),
    ],
  },
  {
    textQuery: 'dentista en Lindavista, Ciudad de México',
    places: [
      lugar('la-clinica-dental-lindavista', 'La Clínica Dental Lindavista', 'Av. Montevideo 272, Lindavista, Gustavo A. Madero, 07300 CDMX', '+52 55 8854 7357', 'https://laclinica.com.mx/contactanos/', { h: { ...LV([9, 20]), 6: [9, 16] } }),
      lugar('navs-dental', "Nav's Dental · Dr. Víctor M. Navarro Sousa", 'Calle Lima 880-A, altos 1, Lindavista, 07300 CDMX', '+52 55 5586 0968', 'https://navsdental.com/contacto', { h: { ...LV([[9.5, 13.5], [16.5, 19.5]]), 6: [9.5, 14] } }),
      lugar('odontosoto', 'Consultorio Dental Odontosoto', 'Salaverry 814, Lindavista, CDMX', '+52 55 6631 2754', 'https://www.odontosoto.com/', { h: { ...LV([11.5, 21]), 6: [11, 16] } }),
      lugar('dentis-lindavista', 'Dentis Lindavista', 'Av. Montevideo 363, local 326, Lindavista, 07300 CDMX', '+52 55 5586 9969', '', { h: { ...LV([10, 20]), 6: [10, 18] } }),
      lugar('mil-sonrisas-lindavista', 'Fundación Mil Sonrisas Lindavista', 'Arequipa, Lindavista, Gustavo A. Madero, 07300 CDMX', '+52 55 5088 8505', '', { h: { ...LV([9, 18]), 6: [9, 18], 0: [9, 18] } }),
    ],
  },
  {
    textQuery: 'dentista en Tlalpan Centro, Ciudad de México',
    places: [
      lugar('dental-advance-tlalpan', 'Dental Advance', 'Calzada de Tlalpan 4836, Barrio Niño Jesús, Tlalpan, CDMX', '+52 55 7706 5212', 'https://draltamirano.mx/', { h: { ...LV([9, 21]), 6: [9, 16] } }),
      lugar('dentistas-en-tlalpan', 'Dentistas en Tlalpan · Dr. Héctor Hernández', 'Av. Renato Leduc 148, Toriello Guerra, Tlalpan, CDMX', '+52 55 7574 2570', 'https://dentistasentlalpan.com/', { h: { ...LV([10, 20]), 6: [9, 15] } }),
      lugar('dental-karand', 'Dental Karand', 'Hacienda del Cristo 130, Coapa, Tlalpan, CDMX', '+52 55 7144 0735', 'https://www.dentalkarand.com/', { h: { ...LV([10, 21]), 6: [10, 21] } }),
      lugar('futura-dental', 'Futura Dental', 'Acanceh 573, Pedregal de San Nicolás, Tlalpan, CDMX', '+52 55 2060 4281', 'https://futuradental.xyz/', { h: LV([11, 19]) }),
      lugar('medica-altaplus', 'Médica AltaPlus · Atención Dental', 'Tizimín 216, Lomas de Padierna, Tlalpan, CDMX', '+52 55 4005 1376', 'https://medaltaplus.com/atencion-dental/', { h: { ...LV([8, 21]), 6: [8, 16], 0: [8, 16] } }),
      lugar('especialidad-dental-padierna', 'Consultorio de Especialidad Dental', 'Lomas de Padierna, Tlalpan, CDMX', '+52 55 2615 4832', 'https://consultorioespecialidaddental.com/'),
      lugar('dental-san-pedro-martir', 'Centro Dental San Pedro Mártir', 'Camino Viejo a San Pedro Mártir 188, Tlalpan, CDMX', '+52 55 5415 9678', '', { h: { ...LV([9, 19]), 6: [9, 19] } }),
    ],
  },
];
