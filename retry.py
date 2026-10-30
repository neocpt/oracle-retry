"""Retry de creation de la VM minecraft-create (Oracle A1 gratuit, Paris).

Une session dure ~5h40 : le workflow la relance a la fin (step Relance).
Les formes sont essayees a tour de role, espacees de PAUSE_S secondes,
avec un backoff sur 429 (« Too many requests for the user »).
Sorties : SUCCES ... (VM creee), DEJA_CREEE ... (VM deja la), ERREUR_CONFIG (auth/parametres).
"""
import datetime
import os
import sys
import time

import oci

SESSION_S = 340 * 60                      # job GitHub limite a 350 min
PAUSE_S = 60                              # entre deux tentatives
BACKOFF_MIN_S, BACKOFF_MAX_S = 180, 900   # sur 429 : double a chaque fois, reset ensuite
FORMES = [(4, 24), (2, 12), (1, 6)]       # (OCPU, Go RAM) par ordre de preference
NOM = "minecraft-create"
CONFIG_ERR = (400, 401, 403, 404)         # inutile de reessayer


def log(msg):
    print(f"{datetime.datetime.now():%H:%M:%S} {msg}", flush=True)


cfg = {"user": os.environ["OCI_USER"], "fingerprint": os.environ["OCI_FP"],
       "tenancy": os.environ["OCI_TENANCY"], "region": "eu-paris-1",
       "key_content": os.environ["OCI_KEY"]}
t = cfg["tenancy"]
cmp = oci.core.ComputeClient(cfg)
net = oci.core.VirtualNetworkClient(cfg)
idn = oci.identity.IdentityClient(cfg)


def existing():
    return [i for i in cmp.list_instances(t, display_name=NOM).data
            if i.lifecycle_state not in ("TERMINATED", "TERMINATING")]


def preparer():
    ad = idn.list_availability_domains(t).data[0].name
    vcn = next(v for v in net.list_vcns(t).data if v.display_name == "vcn-minecraft")
    subnet = next(s for s in net.list_subnets(t, vcn_id=vcn.id).data if s.prohibit_public_ip_on_vnic is False)
    img = cmp.list_images(t, operating_system="Canonical Ubuntu", operating_system_version="22.04",
                          shape="VM.Standard.A1.Flex", sort_by="TIMECREATED", sort_order="DESC").data[0]
    return ad, subnet, img


def lancer(ad, subnet, img, o, m):
    d = oci.core.models.LaunchInstanceDetails(
        availability_domain=ad, compartment_id=t, display_name=NOM,
        shape="VM.Standard.A1.Flex",
        shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(ocpus=o, memory_in_gbs=m),
        source_details=oci.core.models.InstanceSourceViaImageDetails(image_id=img.id, boot_volume_size_in_gbs=100),
        create_vnic_details=oci.core.models.CreateVnicDetails(subnet_id=subnet.id, assign_public_ip=True),
        metadata={"ssh_authorized_keys": os.environ["SSH_PUB"].strip()})
    return cmp.launch_instance(d).data


def main():
    ad, subnet, img = preparer()
    fin = time.time() + SESSION_S
    backoff = BACKOFF_MIN_S
    while time.time() < fin:
        vms = existing()
        if vms:
            print("DEJA_CREEE", vms[0].id, flush=True)
            return 0
        for o, m in FORMES:
            if time.time() >= fin:
                break
            try:
                inst = lancer(ad, subnet, img, o, m)
                print(f"SUCCES {o} OCPU/{m} Go id={inst.id}", flush=True)
                return 0
            except oci.exceptions.ServiceError as e:
                log(f"{o}/{m}: {e.status} {e.message[:60]}")
                if e.status == 429:
                    log(f"429 : pause {backoff}s")
                    time.sleep(backoff)
                    backoff = min(backoff * 2, BACKOFF_MAX_S)
                    continue
                if e.status in CONFIG_ERR:
                    print("ERREUR_CONFIG", e.status, e.message[:200], flush=True)
                    return 2
                backoff = BACKOFF_MIN_S
            except Exception as e:  # reseau, timeout, etc.
                log(f"erreur: {e}")
            time.sleep(PAUSE_S)
    log("FIN_SESSION (relance par le workflow)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
