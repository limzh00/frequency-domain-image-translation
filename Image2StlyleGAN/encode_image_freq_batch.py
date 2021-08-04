from genericpath import exists
import numpy as np 
import matplotlib.pyplot as plt 
from stylegan_layers import  G_mapping,G_synthesis
from read_image import image_reader
import argparse
import torch
import torch.nn as nn
from collections import OrderedDict
import torch.nn.functional as F
from torchvision.utils import save_image
from perceptual_model import VGG16_for_Perceptual
import torch.optim as optim
import os
import sys
sys.path.append("../")
from utils_freq.freq_fourier_loss import fft_L1_loss_color
import utils_freq.freq_pixel_loss as utils_freq
device = 'cuda:0' if torch.cuda.is_available() else 'cpu'


def main():
     parser = argparse.ArgumentParser(description='Find latent representation of reference images using perceptual loss')
     parser.add_argument('--batch_size', default=1, help='Batch size for generator and perceptual model', type=int)
     parser.add_argument('--resolution',default=1024,type=int)
     parser.add_argument('--src_im_list', default="source_image/")
     parser.add_argument('--weight_file',default="weight_files/pytorch/karras2019stylegan-ffhq-1024x1024.pt",type=str)
     parser.add_argument('--iteration',default=5000,type=int) 

     parser.add_argument('--lambda_recon_blur', type=float, default=1,
                         help='Weight for image reconstruction loss blur')
     parser.add_argument('--lambda_recon_fft', type=float, default=1,
                         help='Weight for image reconstruction loss fft ')
     parser.add_argument('--gauss_size', type=int, default=21)
     parser.add_argument('--radius', type=int, default=21)
     parser.add_argument('--w_scale', type=float, default=1)


     save_dir_resize = 'source_image_resize'
     os.makedirs(save_dir_resize, exist_ok = True)

     args=parser.parse_args()

     gauss_kernel = utils_freq.get_gaussian_kernel(args.gauss_size).cuda()

     g_all = nn.Sequential(OrderedDict([
    ('g_mapping', G_mapping()),
    #('truncation', Truncation(avg_latent)),
    ('g_synthesis', G_synthesis(resolution=args.resolution))    
    ]))




     g_all.load_state_dict(torch.load(args.weight_file, map_location=device))
     g_all.eval()
     g_all.to(device)


     g_mapping,g_synthesis=g_all[0],g_all[1]
     list_name = os.listdir(args.src_im_list)
     for image_index, name in enumerate(list_name):
         args.src_im = name
         name=args.src_im.split(".")[0]
         img=image_reader(args.src_im_list+args.src_im,crop_size=0) #(1,3,1024,1024) -1~1
         img=img.to(device)

         MSE_Loss=nn.MSELoss(reduction="mean")

         img_p=img.clone() #Perceptual loss 
         upsample2d=torch.nn.Upsample(scale_factor=256/args.resolution, mode='bilinear') 
         img_p=upsample2d(img_p)

         perceptual_net=VGG16_for_Perceptual(n_layers=[2,4,14,21]).to(device)
         dlatent=torch.zeros((1,18,512),requires_grad=True,device=device)
         optimizer=optim.Adam({dlatent},lr=0.01,betas=(0.9,0.999),eps=1e-8)

         print("Start")
         loss_list=[]
         dirs = 'save'+ args.src_im_list[6:]+'/encode_freq_'+name
         print(dirs)
         if not os.path.exists(dirs):
               os.makedirs(dirs)
         for i in range(args.iteration):
              optimizer.zero_grad()
              synth_img=g_synthesis(dlatent)
              synth_img = (synth_img + 1.0) / 2.0
              mse_loss,perceptual_loss=caluclate_loss(synth_img,img,perceptual_net,img_p,MSE_Loss,upsample2d, gauss_kernel, args)
              loss=mse_loss+perceptual_loss
              loss.backward()

              optimizer.step()

              loss_np=loss.detach().cpu().numpy()
              loss_p=perceptual_loss.detach().cpu().numpy()
              loss_m=mse_loss.detach().cpu().numpy()

              loss_list.append(loss_np)
              if i%10==0:
                         print("image {} iter{}: loss -- {},  recon_loss --{},  percep_loss --{}".format(image_index, i,loss_np,loss_m,loss_p))
              if ( i%4990==0 or i==args.iteration -1 ) and i!= 0: 
                         save_image(synth_img.clamp(0,1),dirs+"/{}.png".format(i)) 
                         np.save("latent_W/{}.npy".format(name),dlatent.detach().cpu().numpy())


def caluclate_loss(synth_img,img,perceptual_net,img_p,MSE_Loss,upsample2d, gauss_kernel, args):
     #calculate MSE Loss
     mse_loss=MSE_Loss(synth_img,img) # (lamda_mse/N)*||G(w)-I||^2

     x_real_freq = utils_freq.find_fake_freq(img, gauss_kernel)  
     x_rec2_freq = utils_freq.find_fake_freq(synth_img, gauss_kernel)
     loss_rec_blur = F.l1_loss(x_rec2_freq, x_real_freq)
     loss_recon_fft = fft_L1_loss_color(synth_img, synth_img)

     mse_loss += args.w_scale * (args.lambda_recon_blur * loss_rec_blur + args.lambda_recon_fft * loss_recon_fft)




     #calculate Perceptual Loss
     real_0,real_1,real_2,real_3=perceptual_net(img_p)
     synth_p=upsample2d(synth_img) #(1,3,256,256)
     synth_0,synth_1,synth_2,synth_3=perceptual_net(synth_p)

     perceptual_loss=0
     perceptual_loss+=MSE_Loss(synth_0,real_0)
     perceptual_loss+=MSE_Loss(synth_1,real_1)
     perceptual_loss+=MSE_Loss(synth_2,real_2)
     perceptual_loss+=MSE_Loss(synth_3,real_3)

     return mse_loss,perceptual_loss




     







     

    

if __name__ == "__main__":
    main()



