# blast for resistance genes, summarise by class (one class per column)
import string, re, collections
import os, sys, subprocess
from optparse import OptionParser
	
def main():

	usage = "usage: %prog [options]"
	parser = OptionParser(usage=usage)

	# options
	parser.add_option("-s", "--seqs", action="store", dest="seqs", help="res gene sequences to screen for", default="ARGannot.r1.fasta")
	parser.add_option("-t", "--class", action="store", dest="res_class_file", help="res gene classes (CSV)", default="ARGannot_clustered80.csv")
	parser.add_option("-q", "--qrdr", action="store", dest="qrdr", help="QRDR sequences", default="")
	parser.add_option("-m", "--minident", action="store", dest="minident", help="Minimum percent identity (default 90)", default="90")
	parser.add_option("-c", "--mincov", action="store", dest="mincov", help="Minimum percent coverage (default 80)", default="80")
	
	return parser.parse_args()
	
# functions for finding snps
def getGappedPosition(seq,pos):
	num_chars = 0
	i = 0
	seq_list = list(seq)
	while num_chars <= pos and i < len(seq):
		if seq[i] != "-":
			num_chars += 1
		i += 1
	return (i-1)
	
def checkSNPs(wt_aa, hit_aa, mutations, sstart, gene_id):

	# write temporary seqs
	s = file("seqs.tmp","w")
	s.write(">wt\n" + wt_aa + "\n")
	s.write(">hit\n" + hit_aa + "\n")
	s.close()

	f = os.popen("edialign seqs.tmp -outfile x -outseq seqs.aln.tmp -auto")

	# read aligned sequences
	f = file("seqs.aln.tmp","r")
	wt_string = ""
	aln_string = ""
	read_wt_seq = False
	read_aln_seq = False
	for line in f:
		if line.startswith(">"):
			if not read_wt_seq:
				read_wt_seq = True # first header 
			else:
				read_aln_seq = True # second header
		else:
			if read_aln_seq:
				aln_string += line.rstrip()
			else:
				wt_string += line.rstrip()	
	f.close()

	snps = []

	for (pos,wt) in mutations:
		if pos > sstart:
			pos_in_aln = getGappedPosition(wt_string,pos - sstart + 1)
			allele_in_aln = aln_string[pos_in_aln-1]
			if allele_in_aln != wt:
				snps.append(gene_id + "-" + str(pos) + allele_in_aln)
			
	return snps

if __name__ == "__main__":

	(options, args) = main()
		
	if options.seqs=="":
		DoError("No res gene sequences provided (-s)")
	else:
		(path,fileName) = os.path.split(options.seqs)
		if not os.path.exists(options.seqs + ".nin"):
			os.system("makeblastdb -dbtype nucl -logfile blast.log -in " + options.seqs)
		
	if options.qrdr!="":
		(qrdr_path,qrdr_fileName) = os.path.split(options.qrdr)
		if not os.path.exists(options.qrdr + ".nin"):
			os.system("makeblastdb -dbtype nucl -logfile blast.log -in " + options.qrdr)
		
	# read table of genes and store classes
	
	gene_info = {} # key = sequence id (fasta header in seq file), value = (allele,class,Bla_Class)
	res_classes = []
	bla_classes = []

	if options.res_class_file=="":
		DoError("No res gene class file provided (-t)")
	else:
		f = file(options.res_class_file,"r")
		header=0
		for line in f:
			if header == 0:
				header = 1
				#seqID,clusterid,gene,allele,cluster_contains_multiple_genes,gene_found_in_multiple_clusters,idInFile,symbol,class,accession,positions,size,Lahey,Bla_Class
			else:
				fields = line.rstrip().split(",")
				(seqID, clusterID, gene, allele, allele_symbol, res_class, bla_class) = (fields[0], fields[1], fields[2], fields[3], fields[3], fields[8], fields[13])
				seq_header = "__".join([clusterID,gene,allele,seqID])
				if res_class == "Bla" and bla_class == "NA":
					bla_class = "Bla"
				gene_info[seq_header] = (allele_symbol, res_class, bla_class)
				if res_class not in res_classes:
					res_classes.append(res_class)
				if bla_class not in bla_classes:
					bla_classes.append(bla_class)
		f.close()
	
	res_classes.sort()
	res_classes.remove("Bla")
	bla_classes.sort()
	bla_classes.remove("NA")
		
	# print header
	print "\t".join(["strain"] + res_classes + bla_classes)

	for contigs in args:
		(dir,fileName) = os.path.split(contigs)
		(name,ext) = os.path.splitext(fileName)

		# blast against all
		f = os.popen("blastn -task blastn -db " + options.seqs + " -query " + contigs + " -outfmt '6 sacc pident slen length score' -ungapped -dust no -evalue 1E-20 -word_size 32 -max_target_seqs 10000 -culling_limit 1 -perc_identity " + options.minident)

		# list of genes in each class with hits
		hits_dict = {} # key = class, value = list
		
		for line in f:
			fields = line.rstrip().split("\t")
			(gene_id,pcid,length,allele_length,score) = (fields[0],float(fields[1]),float(fields[2]),float(fields[3]),float(fields[4]))
			if (allele_length/length*100) > float(options.mincov):
				(hit_allele, hit_class, hit_bla_class) = gene_info[gene_id]
				if hit_class == "Bla":
					hit_class = hit_bla_class
				if pcid < 100.00:
					hit_allele += "*" # imprecise match
				if allele_length < length:
					hit_allele += "?" # partial match
				if hit_class in hits_dict:
					hits_dict[hit_class].append(hit_allele)
				else:
					hits_dict[hit_class] = [hit_allele]
		f.close()
		
		# check for QRDR mutations
		if options.qrdr!="":
		
			# mutations to check for
			qrdr_loci = {'GyrA': [(83,'S'),(87,'D')],'ParC': [(80,'S'),(84,'E')]}
			qrdr_loci_checked = [] # take only the top hit for each seq
			
			f = os.popen("blastx -db " + options.qrdr + " -query " + contigs + " -outfmt '6 sacc sseq qseq gaps slen length sstart' -ungapped -comp_based_stats F -culling_limit 1 -max_hsps 1")
		
			for line in f:
				fields = line.rstrip().split("\t")
				(gene_id,wt_seq,this_seq,gaps,qrdr_length,aln_length,sstart) = (fields[0],fields[1],fields[2],int(fields[3]),int(fields[4]),int(fields[5]),int(fields[6]))
				if gene_id not in qrdr_loci_checked:
					qrdr_loci_checked.append(gene_id)
					if (gaps == 0) and (qrdr_length == aln_length) and (gene_id in qrdr_loci):
						for (pos,wt) in qrdr_loci[gene_id]:
							if this_seq[pos-1] != wt:
								res_allele = gene_id + "-" + str(pos) + this_seq[pos-1]
								if "Flq_SNP" in hits_dict:
									hits_dict["Flq"].append(res_allele)
								else:
									hits_dict["Flq"] = [res_allele]
					else:
						# not a simple alignment, need to align query and hit and extract loci manually
						snps = checkSNPs(wt_seq, this_seq, qrdr_loci[gene_id], sstart, gene_id)
						if len(snps) > 0:
							if "Flq" in hits_dict:
								hits_dict["Flq"] += snps
							else:
								hits_dict["Flq"] = snps
		
		hit_string = [name]
		for res_class in (res_classes + bla_classes):
			if res_class in hits_dict:
				hit_string.append(";".join(hits_dict[res_class]))
			else:
				hit_string.append("-")
				
		print "\t".join(hit_string)