from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import Product, Category, Cart, CartItem, Order, OrderItem
from django.contrib import messages
from django.contrib.auth.models import User
from django.http import JsonResponse,HttpResponseBadRequest
import razorpay
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt


def home(request):
    products = Product.objects.all()
    return render(request, 'home.html', {'products': products})


# Shop_page View
def category_list_view(request):
    """Displays all available categories in a grid."""
    categories = Category.objects.all()

    for category in categories:
        first_product = Product.objects.filter(
            category=category, 
            is_available=True
        ).first()

        if first_product and first_product.image:
            category.image_url = first_product.image.url
        else:
            category.image_url = 'images/placeholder.jpg'
    context = {
        'categories': categories,
        'page_title': 'Shop by Category',
    }
    return render(request, 'categories.html', context)


def shop_view(request, category_slug=None):
    category = None
    products = Product.objects.all()
    all_categories = Category.objects.all()

    if category_slug:
        category = get_object_or_404(Category, slug=category_slug)
        products = products.filter(category=category)
    context = {
        'category': category,
        'products': products,
        'all_categories': all_categories,
        'page_title': category.name if category else 'All Products',
    }
    return render(request, 'shop.html', context)


@login_required
def product_detail(request, pk):
    product = get_object_or_404(Product, pk=pk)
    
    context = {
        'product': product
    }
    return render(request, 'product_detail.html', context)


# Shopping Cart View
@login_required
def add_to_cart(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    cart, created = Cart.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        quantity = int(request.POST.get('quantity', 1))
        # messages.success(request, f"{product.name} added to cart!")
        # return redirect('product_detail', pk=product_id)

        cart_item, item_created = CartItem.objects.get_or_create(
            cart=cart, 
            product=product,
            defaults={'quantity': quantity}
        )

        if not item_created:
            cart_item.quantity += quantity
            cart_item.save()
        messages.success(request, f"{product.name} ({quantity}x) added to cart!")
        return redirect('cart_detail')
    
    return redirect('product_detail.html', pk=product.id)


def cart_detail(request):
    """Retrieves and displays the user's shopping cart contents."""
    try:
        cart = Cart.objects.get(user=request.user)
    except Cart.DoesNotExist:
        cart = None # Cart is empty if it doesn't exist
    
    context = {
        'cart': cart,
    }
    return render(request, 'shopping_cart.html', context)


def remove_from_cart(request, item_id):
    """Removes a specific CartItem from the user's cart."""
    # Ensure the item belongs to the current user's cart
    cart = get_object_or_404(Cart, user=request.user)
    
    try:
        cart_item = CartItem.objects.get(id=item_id, cart=cart)
        cart_item.delete()
        messages.info(request, "Item removed from cart.")
    except CartItem.DoesNotExist:
        messages.error(request, "That item was not found in your cart.")

    return redirect('cart_detail')


# Login/Signup Page View
def signup_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        cpassword = request.POST.get('cpassword')

        if password != cpassword:
            messages.error(request, 'Passwords do not match!')
            return render(request, 'signup.html', {'username': username, 'email': email})

        try:
            if User.objects.filter(username=username).exists():
                messages.error(request, 'Username already taken.')
                return render(request, 'signup.html', {'username': username, 'email': email})

            User.objects.create_user(username=username, email=email, password=password)

            messages.success(request, 'Account created successfully! Please Log in.')
            return redirect('login')

        except Exception as e:
            messages.error(request, f"An unexpected error occurred during signup.")
            return render(request, 'signup.html', {'username': username, 'email': email})
        
    return render(request, 'signup.html')


# Checkout-payment View
def checkout_view(request):
    """
    Handles both rendering the checkout form (GET) and processing the address 
    submission to initiate the payment process (POST).
    """
    # --- STEP 1: INITIAL SETUP & CART VALIDATION ---
    try:
        cart = Cart.objects.get(user=request.user)
    except Cart.DoesNotExist:
        messages.error(request, "Your cart is empty. Please add items before checking out.")
        return redirect('cart_detail')

    if not cart.items.exists():
        messages.error(request, "Your cart is empty. Please add items before checking out.")
        return redirect('cart_detail')

    cart_items = cart.items.all()
    total = cart.get_subtotal()

    if total <= 0:
        messages.error(request, "Cannot checkout with a zero or negative total.")
        return redirect('cart_detail')
    
    amount_paise = max(int(total * 100), 100)  # Ensure minimum 1₹

    # === STEP 2: HANDLE POST REQUEST (Form Submission) ===
    if request.method == 'POST':
        first_name = request.POST.get('firstName', '')
        last_name = request.POST.get('lastName', '')
        email = request.POST.get('email', '')
        phone = request.POST.get('phone', '')
        address = request.POST.get('address', '')
        
        full_name = f"{first_name} {last_name}".strip()
        
        if not all([full_name, email, phone, address]): 
            messages.error(request, "Please fill out all required fields.")
        else:
            try:
                # Create the Order
                new_order = Order.objects.create(
                    user=request.user, 
                    full_name=full_name,
                    email=email,
                    phone_number=phone,
                    shipping_address=address,
                    total_amount=total, 
                )

                # Create OrderItems snapshot
                for cart_item in cart_items:
                    OrderItem.objects.create(
                        order=new_order,
                        product_name=cart_item.product.name,
                        product_price=cart_item.product.price,
                        quantity=cart_item.quantity
                    )
                
                # Create Razorpay Order
                client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
                razorpay_order = client.order.create({
                    'amount': amount_paise,
                    'currency': 'INR',
                    'payment_capture': 1,
                    'notes': {'order_db_id': new_order.id}
                })

                new_order.razorpay_order_id = razorpay_order['id']
                new_order.save()
                
                # Store Razorpay info in session
                request.session['razorpay_data'] = {
                    'order_id': new_order.razorpay_order_id,
                    'amount_paise': amount_paise,
                    'user_phone': phone,
                    'user_name': full_name,
                    'user_email': email,
                }

                # Redirect back to checkout for popup trigger
                return redirect('checkout')

            except Exception as e:
                messages.error(request, f"Error while processing your order: {e}")
                return redirect('cart_detail')

    # === STEP 3: HANDLE GET REQUEST (Page Load or Post-Redirect) ===
    razorpay_data = request.session.pop('razorpay_data', None)
    trigger_payment = bool(razorpay_data)
    user = request.user
    
    if razorpay_data:
        context = {
            'total': total,
            'cart_items': cart_items,
            'amount_paise': razorpay_data['amount_paise'],
            'razorpay_order_id': razorpay_data['order_id'],
            'razorpay_key_id': settings.RAZORPAY_KEY_ID,
            'user_name': razorpay_data.get('user_name', user.get_full_name() or user.username),
            'user_email': razorpay_data.get('user_email', user.email),
            'user_phone': razorpay_data.get('user_phone', ''),
            'trigger_payment': True,
        }
    else:
        context = {
            'cart_items': cart_items,
            'total': total,
            'amount_paise': amount_paise,
            'user_name': user.get_full_name() or user.username,
            'user_email': user.email,
            'user_phone': '',
            'trigger_payment': False,
        }
    
    return render(request, 'checkout.html', context)


@csrf_exempt 
def payment_success(request):
    """
    Verifies the payment and finalizes the order.
    The payment_id is expected via GET query parameters from the checkout.html handler.
    """
    razorpay_payment_id = request.GET.get('payment_id')
    
    # CRITICAL: Attempt to retrieve the most recent unpaid order for this user
    try:
        # We assume the order was created just before the payment attempt
        order = Order.objects.filter(
            user=request.user, 
            is_paid=False
        ).order_by('-created_at').first()
        
        if not order:
            messages.error(request, "No pending order found to finalize.")
            return redirect('home') # Redirect to a safe page

        razorpay_order_id = order.razorpay_order_id

    except Exception:
        messages.error(request, "Error retrieving pending order details.")
        return redirect('home') # Redirect to a safe page


    # --- 1. SIGNATURE VERIFICATION (MOST IMPORTANT SECURITY STEP) ---
    try:
        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

        # Verify the Payment status with Razorpay
        payment_info = client.payment.fetch(razorpay_payment_id)
        
        if payment_info['status'] == 'captured' and payment_info['order_id'] == razorpay_order_id:
            
            # --- 2. ORDER COMPLETION (Payment is verified) ---
            order.razorpay_payment_id = razorpay_payment_id
            order.is_paid = True
            order.save()
            
            # --- 3. CLEAR CART ---
            try:
                cart = Cart.objects.get(user=request.user)
                cart.items.all().delete()
            except Cart.DoesNotExist:
                pass # Cart already empty
                
            messages.success(request, f"Payment successful! Your order #{order.id} has been placed.")
            return render(request, 'success.html', {'order': order})
        
        else:
            # Payment status is not captured or order ID mismatch
            messages.error(request, "Payment verification failed or status is pending.")
            return redirect('checkout') # Allow user to retry payment
            
    except Exception as e:
        messages.error(request, f"Payment verification error: {e}")
        return redirect('checkout')


# Blogs View
def blogs_view(request):
    """
    Renders the blogs.html page.
    """
    return render(request, 'blogs.html')


# Gallery View
def gallery(request):
    """Renders the gallery page with the carousel."""
    return render(request, 'gallery.html')

# Contact Us Page View
def contact(request):
    """Renders the contact page."""
    return render(request, 'contact.html')