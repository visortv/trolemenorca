MENORCA BUS V10.5

CORRECCIÓN DEL PROBLEMA 'ORIGEN PERO SIN DESTINO'

La causa era un snapshot semilla sin recorridos.

Ahora:
- seed_snapshot.json incluye topología conservadora de TODAS las líneas actuales.
- L01 incluye su recorrido completo publicado por TMSA.
- Las otras líneas incluyen como mínimo las poblaciones expresamente indicadas
  en su nombre oficial, en ambos sentidos.
- Las líneas L18, L54 y L73 están marcadas NO OPERATIVAS.
- La sincronización sólo sustituye el snapshot si ha obtenido recorridos utilizables.
- Si TMSA falla, se restaura la topología semilla, no un snapshot vacío.

Por tanto, después de elegir un origen deben aparecer destinos que correspondan
a una línea operativa real. No se inventan conexiones entre poblaciones que no
compartan un recorrido.

Diagnóstico:
http://127.0.0.1:5055/api/debug-topology

Debe mostrar edge_count > 0 y relaciones como:
Maó -> Ciutadella
Maó -> Es Castell
Maó -> Sant Lluís
Ciutadella -> Maó
etc.

Puerto fijo: 5055.
