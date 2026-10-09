"""Une session de retry (~5h40). Verifie d'abord qu'aucune VM minecraft-create n'existe."""
import oci, os, time, sys, datetime

cfg = {"user": os.environ["OCI_USER"], "fingerprint": os.environ["OCI_FP"], "tenancy": os.environ["OCI_TENANCY"],
       "region": "eu-paris-1", "key_content": os.environ["OCI_KEY"]}
t = cfg["tenancy"]
cmp = oci.core.ComputeClient(cfg)
net = oci.core.VirtualNetworkClient(cfg)
idn = oci.identity.IdentityClient(cfg)


def existing():
    return [i for i in cmp.list_instances(t, display_name="minecraft-create").data
            if i.lifecycle_state not in ("TERMINATED", "TERMINATING")]


if existing():
    print("DEJA_CREEE", existing()[0].id)
    sys.exit(0)

ad = idn.list_availability_domains(t).data[0].name
vcn = [v for v in net.list_vcns(t).data if v.display_name == "vcn-minecraft"][0]
subnet = [s for s in net.list_subnets(t, vcn_id=vcn.id).data if s.prohibit_public_ip_on_vnic is False][0]
img = cmp.list_images(t, operating_system="Canonical Ubuntu", operating_system_version="22.04",
                      shape="VM.Standard.A1.Flex", sort_by="TIMECREATED", sort_order="DESC").data[0]
pub = os.environ["SSH_PUB"].strip()
end = time.time() + 340 * 60
while time.time() < end:
    for o, m in [(4, 24), (2, 12), (1, 6)]:
        try:
            d = oci.core.models.LaunchInstanceDetails(
                availability_domain=ad, compartment_id=t, display_name="minecraft-create",
                shape="VM.Standard.A1.Flex",
                shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(ocpus=o, memory_in_gbs=m),
                source_details=oci.core.models.InstanceSourceViaImageDetails(image_id=img.id, boot_volume_size_in_gbs=100),
                create_vnic_details=oci.core.models.CreateVnicDetails(subnet_id=subnet.id, assign_public_ip=True),
                metadata={"ssh_authorized_keys": pub})
            inst = cmp.launch_instance(d).data
            print(f"SUCCES {o} OCPU/{m} Go id={inst.id}")
            sys.exit(0)
        except oci.exceptions.ServiceError as e:
            print(f"{datetime.datetime.now():%H:%M:%S} {o}/{m}: {e.status} {e.message[:50]}", flush=True)
            time.sleep(120 if e.status == 429 else 30)
    time.sleep(60)
