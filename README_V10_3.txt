MENORCA BUS V10.3

DESTINOS ESTRICTAMENTE VIABLES

Se elimina el fallback que deducía destinos por el nombre de la línea.

Un destino aparece sólo si:
1. La línea está operativa.
2. El recorrido sincronizado contiene origen antes que destino.
3. Si existe una matriz horaria válida para la fecha, hay al menos una expedición
   con hora real tanto en origen como en destino.

Si no puede demostrarse que el destino es viable, NO se muestra.

También la población de origen sólo aparece si tiene al menos una salida real
según la topología sincronizada.

Puerto fijo:
http://127.0.0.1:5055/
