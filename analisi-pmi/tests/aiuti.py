"""Generatore di istanze XBRL di prova con i nomi reali della tassonomia itcc-ci."""

TESTA = """<?xml version="1.0" encoding="UTF-8"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:link="http://www.xbrl.org/2003/linkbase"
 xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
 xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
 xmlns:itcc-ci="http://www.infocamere.it/itnn/fr/itcc/ci/2018-11-04">
<link:schemaRef xlink:type="simple" xlink:href="SCHEMA"/>
"""


def contesto(cid, anno, istante=True, dimensione=False):
    periodo = (f"<instant>{anno}-12-31</instant>" if istante
               else f"<startDate>{anno}-01-01</startDate><endDate>{anno}-12-31</endDate>")
    dim = ('<xbrldi:explicitMember dimension="itcc-ci:DipendentiDimension">itcc-ci:Totale</xbrldi:explicitMember>'
           if dimensione else "")
    return (f'<context id="{cid}"><entity><identifier scheme="http://www.infocamere.it">01234567890</identifier></entity>'
            f'<period>{periodo}</period><scenario><itcc-ci:scen>itcc-ci:depositato</itcc-ci:scen>{dim}</scenario></context>\n')


def fatto(nome, ctx, valore, unita="eur"):
    return f'<itcc-ci:{nome} contextRef="{ctx}" unitRef="{unita}" decimals="0">{valore}</itcc-ci:{nome}>\n'


def istanza(abbreviato=False):
    x = TESTA.replace("SCHEMA", "itcc-ci-abb-2018-11-04.xsd" if abbreviato else "itcc-ci-2018-11-04.xsd")
    x += '<unit id="eur"><measure>iso4217:EUR</measure></unit><unit id="pure"><measure>xbrli:pure</measure></unit>\n'
    for anno in (2024, 2025):
        x += contesto(f"i{anno}", anno) + contesto(f"d{anno}", anno, istante=False)
        x += contesto(f"dd{anno}", anno, istante=False, dimensione=True)
    x += '<itcc-ci:DatiAnagraficiDenominazione contextRef="i2025">PROVA SRL</itcc-ci:DatiAnagraficiDenominazione>\n'
    x += '<itcc-ci:DatiAnagraficiCodiceFiscale contextRef="i2025">01234567890</itcc-ci:DatiAnagraficiCodiceFiscale>\n'
    for anno, k in ((2024, 1.0), (2025, 1.1)):
        i, d = f"i{anno}", f"d{anno}"
        x += fatto("TotaleAttivo", i, int(1_000_000 * k))
        x += fatto("TotaleDisponibilitaLiquide", i, int(100_000 * k))
        x += fatto("TotaleAttivoCircolante", i, int(600_000 * k))
        x += fatto("TotalePatrimonioNetto", i, int(300_000 * k))
        x += fatto("PatrimonioNettoCapitale", i, 50_000)
        x += fatto("TrattamentoFineRapportoLavoroSubordinato", i, int(80_000 * k))
        x += fatto("TotaleDebiti", i, int(620_000 * k))
        if abbreviato:
            x += fatto("DebitiEsigibiliEntroEsercizioSuccessivo", i, int(400_000 * k))
            x += fatto("CostiProduzioneAmmortamentiSvalutazioniAmmortamentoImmobilizzazioniImmaterialiMaterialiAltreSvalutazioniImmobilizzazioni", d, 30_000)
            x += fatto("CostiProduzioneAmmortamentiSvalutazioniSvalutazioniCreditiCompresiAttivoCircolanteDisponibilitaLiquide", d, 5_000)
        else:
            x += fatto("DebitiDebitiVersoBancheEsigibiliEntroEsercizioSuccessivo", i, int(150_000 * k))
            x += fatto("DebitiDebitiVersoFornitoriEsigibiliEntroEsercizioSuccessivo", i, int(250_000 * k))
            x += fatto("DebitiDebitiVersoBancheEsigibiliOltreEsercizioSuccessivo", i, int(220_000 * k))
            x += fatto("DebitiDebitiVersoBancheTotaleDebitiVersoBanche", i, int(370_000 * k))
            x += fatto("CostiProduzioneAmmortamentiSvalutazioniTotaleAmmortamentiSvalutazioni", d, 35_000)
        x += fatto("ValoreProduzioneRicaviVenditePrestazioni", d, int(2_000_000 * k))
        x += fatto("TotaleValoreProduzione", d, int(2_050_000 * k))
        x += fatto("TotaleCostiProduzione", d, int(1_950_000 * k))
        x += fatto("DifferenzaValoreCostiProduzione", d, int(100_000 * k))
        x += fatto("ProventiOneriFinanziariInteressiAltriOneriFinanziariTotaleInteressiAltriOneriFinanziari", d, 12_000)
        x += fatto("UtilePerditaEsercizio", d, int(-20_000 if anno == 2024 else 55_000))
        x += fatto("TotaleDipendentiNumeroMedio", f"dd{anno}", 12 if anno == 2025 else 11, "pure")
        # fatto con dimensione su una voce di bilancio: va ignorato
        x += fatto("TotaleAttivo", f"dd{anno}", 1)
    return (x + "</xbrl>\n").encode("utf-8")
